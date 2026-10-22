// Component test: synthetic mouse events do not send input to the user's desktop.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using TarnishedCompanion.Native;

class NativeInteractionTest
{
    private static void Mouse(LayeredOverlay overlay, string method, int x, int y)
    {
        typeof(LayeredOverlay).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic)
            .Invoke(overlay, new object[] { new MouseEventArgs(MouseButtons.Left, 1, x, y, 0) });
    }

    [STAThread]
    static void Main()
    {
        using (LayeredOverlay overlay = new LayeredOverlay(-10000, -10000))
        using (Bitmap bitmap = new Bitmap(320, 200))
        using (MemoryStream png = new MemoryStream())
        {
            bitmap.Save(png, ImageFormat.Png);
            overlay.SetFrame(png.ToArray());
            overlay.SetInteractiveRegions(new double[] { 120, 5, 25, 25 }, 160, 100);
            int clicks = 0;
            double expectedY = 15;
            overlay.ClickRequested += delegate(double x, double y) {
                if (Math.Abs(x - 125) > .001 || Math.Abs(y - expectedY) > .001)
                    throw new Exception("Click was not mapped from PNG pixels to CSS pixels.");
                ++clicks;
            };
            Mouse(overlay, "OnMouseDown", 250, 30);
            Mouse(overlay, "OnMouseUp", 250, 30);
            if (clicks != 1) throw new Exception("A button click was lost.");
            Mouse(overlay, "OnMouseDown", 250, 30);
            Mouse(overlay, "OnMouseUp", 300, 30);
            if (clicks != 1) throw new Exception("Releasing outside a button triggered it.");
            Mouse(overlay, "OnMouseDown", 250, 30);
            Mouse(overlay, "OnMouseUp", 280, 30);
            if (clicks != 1) throw new Exception("Dragging across a button triggered it.");
            using (Bitmap taller = new Bitmap(320, 400))
            using (MemoryStream tallerPng = new MemoryStream())
            {
                taller.Save(tallerPng, ImageFormat.Png);
                overlay.SetFrame(tallerPng.ToArray());
                overlay.SetInteractiveRegions(new double[] { 120, 155, 25, 25 }, 160, 200);
                expectedY = 165;
                Mouse(overlay, "OnMouseDown", 250, 330);
                Mouse(overlay, "OnMouseUp", 250, 330);
                if (clicks != 2) throw new Exception("Vertical resize lost the button's CSS coordinates.");
            }
            overlay.SetInteractiveRegions(new double[0], 160, 200);
            Mouse(overlay, "OnMouseDown", 250, 30);
            Mouse(overlay, "OnMouseUp", 250, 30);
            if (clicks != 2) throw new Exception("A removed button remained clickable.");
        }
        Console.WriteLine("Native interaction passed: DPI mapping, button click, cancelled release, drag, vertical resize, removed control.");
    }
}
