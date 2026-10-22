// Copyright 2026. GPL-3.0-or-later. See ../../LICENSE.txt.
// Presents the shared browser overlay with per-pixel alpha on Windows.
using System;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace TarnishedCompanion.Native
{
    public sealed class LayeredOverlay : Form
    {
        private const int WsExLayered = 0x00080000;
        private const int WmLeftButtonDown = 0x0201;
        private const int WmNcLeftButtonDown = 0x00A1;
        private const int HtCaption = 2;
        private const uint UlwAlpha = 0x00000002;
        private readonly int ownerThread;
        private readonly object frameLock = new object();
        private byte[] lastPixels;
        private RectangleF[] interactiveRegions = new RectangleF[0];
        private double cssWidth;
        private double cssHeight;
        private Point? pressedPoint;
        private RectangleF pressedRegion;

        public event Action<double, double> ClickRequested;

        public int LastWidth { get; private set; }
        public int LastHeight { get; private set; }
        public long FrameCount { get; private set; }

        public LayeredOverlay(int x, int y)
        {
            ownerThread = Thread.CurrentThread.ManagedThreadId;
            Text = "Tarnished Companion";
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = true;
            TopMost = true;
            KeyPreview = true;
            AutoScaleMode = AutoScaleMode.None;
            Location = new Point(x, y);
            Size = new Size(1, 1);
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams parameters = base.CreateParams;
                parameters.ExStyle |= WsExLayered;
                return parameters;
            }
        }

        // Windows retains the image supplied by UpdateLayeredWindow. Ordinary
        // WinForms background painting must not replace its alpha channel.
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e) { }

        protected override bool ProcessCmdKey(ref Message message, Keys keys)
        {
            if (keys == Keys.Escape || keys == (Keys.Alt | Keys.F4))
            {
                Close();
                return true;
            }
            return base.ProcessCmdKey(ref message, keys);
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == WmLeftButtonDown)
            {
                long packed = message.LParam.ToInt64();
                Point point = new Point((short)(packed & 0xffff), (short)((packed >> 16) & 0xffff));
                RectangleF region;
                if (!TryInteractiveRegion(point, out region))
                {
                    pressedPoint = null;
                    ReleaseCapture();
                    SendMessage(Handle, WmNcLeftButtonDown, new IntPtr(HtCaption), IntPtr.Zero);
                    return;
                }
            }
            base.WndProc(ref message);
        }

        // Rectangles arrive in CSS pixels. The captured PNG can have a different
        // scale on high-DPI displays, so every hit is mapped through its viewport.
        public void SetInteractiveRegions(double[] rectangles, double viewportWidth, double viewportHeight)
        {
            if (Thread.CurrentThread.ManagedThreadId != ownerThread)
                throw new InvalidOperationException("Update controls on the window's UI thread.");
            if (rectangles == null || rectangles.Length % 4 != 0 || rectangles.Length > 256 ||
                double.IsNaN(viewportWidth) || double.IsInfinity(viewportWidth) || viewportWidth <= 0 ||
                double.IsNaN(viewportHeight) || double.IsInfinity(viewportHeight) || viewportHeight <= 0)
                throw new ArgumentException("A valid CSS viewport and control rectangles are required.");
            RectangleF[] regions = new RectangleF[rectangles.Length / 4];
            for (int i = 0; i < regions.Length; ++i)
            {
                int offset = i * 4;
                for (int j = 0; j < 4; ++j)
                    if (double.IsNaN(rectangles[offset + j]) || double.IsInfinity(rectangles[offset + j]))
                        throw new ArgumentException("Control coordinates must be finite.");
                if (rectangles[offset + 2] < 0 || rectangles[offset + 3] < 0)
                    throw new ArgumentException("Control sizes cannot be negative.");
                regions[i] = new RectangleF((float)rectangles[offset], (float)rectangles[offset + 1],
                    (float)rectangles[offset + 2], (float)rectangles[offset + 3]);
            }
            cssWidth = viewportWidth;
            cssHeight = viewportHeight;
            interactiveRegions = regions;
        }

        private PointF CssPoint(Point point)
        {
            return new PointF((float)(point.X * cssWidth / Math.Max(1, LastWidth)),
                (float)(point.Y * cssHeight / Math.Max(1, LastHeight)));
        }

        private bool TryInteractiveRegion(Point point, out RectangleF region)
        {
            PointF css = CssPoint(point);
            if (LastWidth > 0 && LastHeight > 0 && cssWidth > 0 && cssHeight > 0)
                foreach (RectangleF candidate in interactiveRegions)
                    if (candidate.Contains(css))
                    {
                        region = candidate;
                        return true;
                    }
            region = RectangleF.Empty;
            return false;
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            RectangleF region;
            if (e.Button == MouseButtons.Left && TryInteractiveRegion(e.Location, out region))
            {
                pressedPoint = e.Location;
                pressedRegion = region;
                Capture = true;
            }
            base.OnMouseDown(e);
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            RectangleF region;
            Cursor = TryInteractiveRegion(e.Location, out region) ? Cursors.Hand : Cursors.Default;
            base.OnMouseMove(e);
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            Point? start = pressedPoint;
            pressedPoint = null;
            Capture = false;
            if (e.Button == MouseButtons.Left && start.HasValue)
            {
                PointF css = CssPoint(e.Location);
                RectangleF current;
                Size tolerance = SystemInformation.DragSize;
                if (Math.Abs(e.X - start.Value.X) <= tolerance.Width &&
                    Math.Abs(e.Y - start.Value.Y) <= tolerance.Height &&
                    pressedRegion.Contains(css) && TryInteractiveRegion(e.Location, out current))
                {
                    Action<double, double> click = ClickRequested;
                    if (click != null)
                        click(css.X, css.Y);
                }
            }
            base.OnMouseUp(e);
        }

        protected override void OnMouseCaptureChanged(EventArgs e)
        {
            if (!Capture)
                pressedPoint = null;
            base.OnMouseCaptureChanged(e);
        }

        public int AlphaAt(int x, int y)
        {
            lock (frameLock)
            {
                if (lastPixels == null || x < 0 || y < 0 || x >= LastWidth || y >= LastHeight)
                    throw new ArgumentOutOfRangeException("x", "The point must be inside the last frame.");
                return lastPixels[(y * LastWidth + x) * 4 + 3];
            }
        }

        public void SetFrame(byte[] png)
        {
            if (png == null || png.Length == 0)
                throw new ArgumentException("A PNG frame is required.", "png");
            if (IsDisposed || Disposing)
                return;
            if (Thread.CurrentThread.ManagedThreadId != ownerThread)
            {
                if (!IsHandleCreated)
                    throw new InvalidOperationException("Create the window handle on its UI thread before submitting frames.");
                Invoke(new Action<byte[]>(SetFrame), new object[] { png });
                return;
            }

            int width;
            int height;
            byte[] pixels;
            using (MemoryStream stream = new MemoryStream(png, false))
            using (Image decoded = Image.FromStream(stream, true, true))
            {
                width = decoded.Width;
                height = decoded.Height;
                int rowBytes = checked(width * 4);
                pixels = new byte[checked(rowBytes * height)];
                using (Bitmap premultiplied = new Bitmap(width, height, PixelFormat.Format32bppPArgb))
                {
                    using (Graphics graphics = Graphics.FromImage(premultiplied))
                    {
                        graphics.CompositingMode = CompositingMode.SourceCopy;
                        graphics.Clear(Color.Transparent);
                        graphics.DrawImageUnscaled(decoded, 0, 0);
                    }
                    BitmapData bitmapData = premultiplied.LockBits(
                        new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly,
                        PixelFormat.Format32bppPArgb);
                    try
                    {
                        for (int row = 0; row < height; ++row)
                            Marshal.Copy(IntPtr.Add(bitmapData.Scan0, checked(row * bitmapData.Stride)),
                                pixels, row * rowBytes, rowBytes);
                    }
                    finally
                    {
                        premultiplied.UnlockBits(bitmapData);
                    }
                }
            }

            Present(pixels, width, height);
            lock (frameLock)
            {
                lastPixels = pixels;
                LastWidth = width;
                LastHeight = height;
                ++FrameCount;
            }
        }

        private void Present(byte[] pixels, int width, int height)
        {
            IntPtr screenDc = GetDC(IntPtr.Zero);
            if (screenDc == IntPtr.Zero)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "GetDC failed.");
            IntPtr memoryDc = IntPtr.Zero;
            IntPtr bitmap = IntPtr.Zero;
            IntPtr previousBitmap = IntPtr.Zero;
            try
            {
                memoryDc = CreateCompatibleDC(screenDc);
                if (memoryDc == IntPtr.Zero)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateCompatibleDC failed.");
                BitmapInfo info = new BitmapInfo();
                info.Header.Size = (uint)Marshal.SizeOf(typeof(BitmapInfoHeader));
                info.Header.Width = width;
                info.Header.Height = -height; // Top-down, matching the decoded frame.
                info.Header.Planes = 1;
                info.Header.BitCount = 32;
                info.Header.SizeImage = (uint)pixels.Length;
                IntPtr bits;
                bitmap = CreateDIBSection(memoryDc, ref info, 0, out bits, IntPtr.Zero, 0);
                if (bitmap == IntPtr.Zero || bits == IntPtr.Zero)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateDIBSection failed.");
                Marshal.Copy(pixels, 0, bits, pixels.Length);
                previousBitmap = SelectObject(memoryDc, bitmap);
                if (previousBitmap == IntPtr.Zero || previousBitmap == new IntPtr(-1))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "SelectObject failed.");

                // Keep WinForms' cached bounds aligned with the native frame.
                // In particular, Show() after the first SetFrame must retain
                // this size rather than reapply the initial 1 x 1 dimensions.
                IntPtr windowHandle = Handle;
                if (Width != width || Height != height)
                    Size = new Size(width, height);
                NativeRect current;
                if (!GetWindowRect(windowHandle, out current))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "GetWindowRect failed.");
                NativePoint destination = new NativePoint(current.Left, current.Top);
                NativePoint source = new NativePoint(0, 0);
                NativeSize size = new NativeSize(width, height);
                BlendFunction blend = new BlendFunction();
                blend.SourceConstantAlpha = 255;
                blend.AlphaFormat = 1; // AC_SRC_ALPHA: each pixel carries its own alpha.
                if (!UpdateLayeredWindow(windowHandle, screenDc, ref destination, ref size,
                    memoryDc, ref source, 0, ref blend, UlwAlpha))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "UpdateLayeredWindow failed.");
            }
            finally
            {
                if (previousBitmap != IntPtr.Zero && previousBitmap != new IntPtr(-1))
                    SelectObject(memoryDc, previousBitmap);
                if (bitmap != IntPtr.Zero)
                    DeleteObject(bitmap);
                if (memoryDc != IntPtr.Zero)
                    DeleteDC(memoryDc);
                ReleaseDC(IntPtr.Zero, screenDc);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                lock (frameLock)
                    lastPixels = null;
            }
            base.Dispose(disposing);
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativePoint
        {
            public int X, Y;
            public NativePoint(int x, int y) { X = x; Y = y; }
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct NativeSize
        {
            public int Width, Height;
            public NativeSize(int width, int height) { Width = width; Height = height; }
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct NativeRect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct BlendFunction
        {
            public byte BlendOperation, BlendFlags, SourceConstantAlpha, AlphaFormat;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapInfoHeader
        {
            public uint Size;
            public int Width, Height;
            public ushort Planes, BitCount;
            public uint Compression, SizeImage;
            public int XPelsPerMeter, YPelsPerMeter;
            public uint ColorsUsed, ColorsImportant;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapInfo { public BitmapInfoHeader Header; public uint Colors; }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr GetDC(IntPtr window);
        [DllImport("user32.dll")]
        private static extern int ReleaseDC(IntPtr window, IntPtr dc);
        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);
        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapInfo info,
            uint usage, out IntPtr bits, IntPtr section, uint offset);
        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr item);
        [DllImport("gdi32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteObject(IntPtr item);
        [DllImport("gdi32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteDC(IntPtr dc);
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetWindowRect(IntPtr window, out NativeRect rectangle);
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool UpdateLayeredWindow(IntPtr window, IntPtr destinationDc,
            ref NativePoint destination, ref NativeSize size, IntPtr sourceDc,
            ref NativePoint source, uint colorKey, ref BlendFunction blend, uint flags);
        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ReleaseCapture();
        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    }
}
