"""Optional external READ-ONLY Windows reader for offline Elden Ring.

No DLL injection, writes, remote threads, debug privileges or anti-cheat bypass.
Layout reference: fromsoftware-rs CSFeManImp / TagHudData (MIT/Apache-2.0).
The included profile is pinned to the SHA-256 of version 2.7.2.0.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import struct
import secrets
from pathlib import Path

K = C.WinDLL('kernel32', use_last_error=True)
INVALID = C.c_void_p(-1).value

class PROCESSENTRY32W(C.Structure):
    _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),('th32DefaultHeapID',C.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]

class MODULEENTRY32W(C.Structure):
    _fields_=[('dwSize',W.DWORD),('th32ModuleID',W.DWORD),('th32ProcessID',W.DWORD),('GlblcntUsage',W.DWORD),('ProccntUsage',W.DWORD),('modBaseAddr',C.c_void_p),('modBaseSize',W.DWORD),('hModule',W.HMODULE),('szModule',W.WCHAR*256),('szExePath',W.WCHAR*260)]

K.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]; K.CreateToolhelp32Snapshot.restype=W.HANDLE
K.Process32FirstW.argtypes=[W.HANDLE,C.POINTER(PROCESSENTRY32W)]; K.Process32NextW.argtypes=K.Process32FirstW.argtypes
K.Module32FirstW.argtypes=[W.HANDLE,C.POINTER(MODULEENTRY32W)]; K.Module32NextW.argtypes=K.Module32FirstW.argtypes
K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]; K.OpenProcess.restype=W.HANDLE
K.CloseHandle.argtypes=[W.HANDLE]
K.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]; K.ReadProcessMemory.restype=W.BOOL

def process_list():
    h=K.CreateToolhelp32Snapshot(2,0)
    if h==INVALID: raise OSError('Cannot inspect running processes; live reader is blocked.')
    try:
        entry=PROCESSENTRY32W(); entry.dwSize=C.sizeof(entry)
        if not K.Process32FirstW(h,C.byref(entry)): raise OSError('Cannot enumerate processes; live reader is blocked.')
        out=[]
        while True:
            out.append((entry.th32ProcessID,entry.szExeFile.lower()))
            if not K.Process32NextW(h,C.byref(entry)): break
        return out
    finally: K.CloseHandle(h)

def eac_present(processes):
    return any('easyanticheat' in name or name=='start_protected_game.exe' for _,name in processes)

def module_info(pid):
    h=K.CreateToolhelp32Snapshot(0x18,pid)
    if h==INVALID: raise OSError('Cannot inspect Elden Ring modules. Keep live mode off for protected sessions.')
    try:
        e=MODULEENTRY32W(); e.dwSize=C.sizeof(e)
        if not K.Module32FirstW(h,C.byref(e)): raise OSError('Game modules are not ready.')
        main=None
        while True:
            if 'easyanticheat' in e.szModule.lower(): raise OSError('EAC module detected; live reader is blocked.')
            if e.szModule.lower()=='eldenring.exe': main=(e.modBaseAddr,e.modBaseSize,e.szExePath)
            if not K.Module32NextW(h,C.byref(e)):break
        if not main:raise OSError('Elden Ring module not found.')
        return main
    finally:K.CloseHandle(h)

def unpack_tags(read, fe, module_base, vtable):
    if struct.unpack('<Q',read(fe,8))[0] != module_base+vtable:
        raise ValueError('Game UI object changed; waiting for a valid instance.')
    hud=read(fe+0x78,1)[0]
    if hud>3:raise ValueError('Unsupported game UI layout.')
    displays=read(fe+0x5BF0,0x60)
    handles={struct.unpack_from('<Q',displays,i*0x20+8)[0] for i in range(3) if struct.unpack_from('<I',displays,i*0x20+8)[0] != 0xFFFFFFFF}
    tags=read(fe+0x1B90,0x128*3)
    bars=[]
    for i in range(3):
        b=tags[i*0x128:(i+1)*0x128]
        handle=struct.unpack_from('<Q',b,8)[0]
        if b[0]!=1 or handle not in handles:continue
        hp=struct.unpack_from('<I',b,0x18)[0]
        difference,max_uncapped=struct.unpack_from('<II',b,0x20)
        maxhp=max_uncapped-difference
        if not 0<=hp<=maxhp<=100000000 or maxhp==0:continue
        menu=b[0x28:0x60]
        length=struct.unpack_from('<Q',menu,0x20)[0]
        capacity=struct.unpack_from('<Q',menu,0x28)[0]
        name=''
        if 0<length<=128 and length<=capacity:
            ptr=struct.unpack_from('<Q',menu,0x10)[0]
            raw=menu[0x10:0x10+length*2] if capacity<8 else read(ptr,length*2)
            name=raw.decode('utf-16-le').split('\0')[0]
        elif struct.unpack_from('<Q',menu,0)[0]:
            # Bounded static string read: stop at its terminator and never scan unbounded memory.
            ptr=struct.unpack_from('<Q',menu,0)[0]
            raw=bytearray()
            for j in range(128):
                unit=read(ptr+j*2,2)
                if unit==b'\0\0':break
                raw.extend(unit)
            name=raw.decode('utf-16-le')
        if name and len(name)<=128 and all(c.isprintable() or c=='\n' for c in name):
            bars.append(dict(name=name,hp=hp,maxHp=maxhp,handle=str(handle)))
    return bars

def unpack_enemy_tags(read, fe):
    """Read only the eight enemy HUD slots, excluding friendly/player tags.

    An enemy's name is not supplied by this HUD. Never interpret another string
    or a player tag as an enemy identity. Handles keep measurements separate.
    """
    displays = read(fe + 0x59F0, 0x40 * 8)
    handles = {struct.unpack_from('<Q', displays, i * 0x40)[0]
               for i in range(8) if displays[i * 0x40 + 0x34] == 1}
    tags = read(fe + 0x1250, 0x128 * 8)
    enemies = []
    for i in range(8):
        b = tags[i * 0x128:(i + 1) * 0x128]
        handle = struct.unpack_from('<Q', b, 8)[0]
        if b[0] != 1 or handle not in handles or handle & 0xFFFFFFFF == 0xFFFFFFFF:
            continue
        hp = struct.unpack_from('<I', b, 0x18)[0]
        difference, uncapped = struct.unpack_from('<II', b, 0x20)
        maximum = uncapped - difference
        if 0 <= hp <= maximum <= 100000000 and maximum > 0:
            enemies.append(dict(name='Enemy target', hp=hp, maxHp=maximum,
                                handle=str(handle), kind='enemy'))
    return enemies


# Explicit hostile teams from the Elden Ring EMEDF TeamType enum. Friendly
# NPCs, spirit allies, players, objects and unverified team IDs are excluded.
HOSTILE_TEAMS = frozenset((6, 7, 9, 13, 21, 23, 24, 25, 27, 29, 33))


def unpack_world_enemies(read, world, module_base, module_size, profile):
    """Bounded read of the supported build's loaded-character distance list."""
    if struct.unpack('<Q', read(world, 8))[0] != module_base + profile['vtable']:
        raise ValueError('Unsupported loaded-character layout.')
    _, first, last, end = struct.unpack('<QQQQ', read(world + profile['distanceVector'], 32))
    if first == last == end == 0:
        return []
    if not 0x10000 <= first <= last <= end < 0x7FFFFFFFFFFF:
        raise ValueError('Invalid loaded-character list.')
    if (last - first) % 16 or (end - first) % 16 or (end - first) // 16 > 4096:
        raise ValueError('Unsupported loaded-character list capacity.')
    count = (last - first) // 16
    if count > 1024:
        raise ValueError('Loaded-character list exceeds the supported read bound.')
    entries = b''.join(read(first + offset, min(4096, count * 16 - offset))
                       for offset in range(0, count * 16, 4096))
    result = []
    seen = set()
    for index in range(count):
        pointer = struct.unpack_from('<Q', entries, index * 16)[0]
        if pointer in seen:
            continue
        seen.add(pointer)
        try:
            character = read(pointer, 0x1C8)
            vtable, handle = struct.unpack_from('<QQ', character)
            kind = struct.unpack_from('<i', character, 0x68)[0]
            if (not module_base <= vtable < module_base + module_size
                    or kind not in (5, 6, 7, 20, 21) or character[0x6C] not in HOSTILE_TEAMS
                    or handle & 0xFFFFFFFF == 0xFFFFFFFF):
                continue
            modules = struct.unpack_from('<Q', character, 0x190)[0]
            data = struct.unpack('<Q', read(modules, 8))[0]
            attributes = read(data, 0x140)
            data_vtable, owner = struct.unpack_from('<QQ', attributes)
            hp, maximum = struct.unpack_from('<ii', attributes, 0x138)
            if (owner == pointer and module_base <= data_vtable < module_base + module_size
                    and 0 <= hp <= maximum <= 100000000 and maximum > 0):
                # Death/reward flags distinguish actual deaths from temporary
                # zero-HP states (for example, enemies preparing to revive).
                defeated=bool(character[0x1C5] & 0x80 or character[0x1C6] & 3)
                result.append(dict(handle=str(handle), instance=str(pointer), hp=hp, maxHp=maximum,
                                   defeated=defeated))
        except (OSError, ValueError):
            # Objects can unload between reads; disappearance is not a death.
            continue
    return result

class LiveReader:
    def __init__(self,profile):
        self.profile=profile; self.handle=None; self.pid=None; self.fe=None; self.base=0;self.unsupported_pid=None;self.combat_bars=[];self.combat_handle=None
        self.module_size=0;self.npc_samples=[];self.npc_session=None;self.npc_status='Waiting for live enemy data.'
    def close(self):
        if self.handle:K.CloseHandle(self.handle)
        self.handle=None; self.pid=None; self.fe=None
        self.combat_bars=[];self.combat_handle=None
        self.npc_samples=[];self.npc_session=None;self.npc_status='Live enemy tracking is paused.'

    def poll_npcs(self):
        self.npc_samples=[]
        profile=self.profile.get('eliminations')
        if not isinstance(profile,dict):
            self.npc_status='This game profile does not support elimination tracking.'
            return
        try:
            world=struct.unpack('<Q',self.read(self.base+profile['singleton'],8))[0]
            self.npc_samples=unpack_world_enemies(self.read,world,self.base,self.module_size,profile)
            self.npc_status='Live enemy data connected.'
        except (OSError,ValueError):
            self.npc_status='Waiting for valid loaded-enemy data.'
    def read(self,addr,size):
        if not 0x10000<=addr<0x7FFFFFFFFFFF or not 0<size<=4096:
            raise ValueError('Invalid or unsupported game pointer.')
        b=C.create_string_buffer(size); count=C.c_size_t()
        if not K.ReadProcessMemory(self.handle,addr,b,size,C.byref(count)) or count.value!=size:
            raise OSError('Game data is not available yet.')
        return b.raw
    def poll(self):
        procs=process_list()
        if eac_present(procs):
            self.close()
            return [],'BLOCKED: EAC or the protected game launcher is running.'
        ids=[pid for pid,name in procs if name=='eldenring.exe']
        if len(ids)!=1:
            self.close();return [],'Waiting for one offline Elden Ring session.'
        pid=ids[0]
        if pid==self.unsupported_pid:
            return [],'Unsupported game build. Save tracking still works; live profile supports 2.7.2.0.'
        if pid!=self.pid:
            self.close()
            base,size,path=module_info(pid)
            with open(path,'rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            if digest!=self.profile['sha256']:
                self.unsupported_pid=pid
                return [],'Unsupported game build. Save tracking still works; live profile supports 2.7.2.0.'
            # Recheck after hashing and before requesting any read access.
            if eac_present(process_list()):return [],'BLOCKED: EAC detected.'
            h=K.OpenProcess(0x0010|0x1000,False,pid) # VM_READ + QUERY_LIMITED_INFORMATION only
            if not h:raise OSError('Read access was refused. No privileges were elevated.')
            self.handle=h;self.pid=pid;self.base=base;self.module_size=size;self.npc_session=secrets.token_hex(16)
        if self.fe is None:
            matches=set()
            for rva in self.profile['singletons']:
                try:
                    ptr=struct.unpack('<Q',self.read(self.base+rva,8))[0]
                    if struct.unpack('<Q',self.read(ptr,8))[0]==self.base+self.profile['vtable']:matches.add(ptr)
                except (OSError,ValueError):pass
            if len(matches)!=1:return [],'Waiting for game UI to load (live reader is experimental).'
            self.fe=matches.pop()
        try:
            self.poll_npcs()
            bars=unpack_tags(self.read,self.fe,self.base,self.profile['vtable'])
            # Boss HP remains the source for encounter detection. Ordinary enemy
            # HUD targets feed combat estimates only, never boss timers/routes.
            enemies = unpack_enemy_tags(self.read, self.fe) if not bars else []
            # A lingering zero-HP tag from a different enemy must not replace
            # the result of the target we actually observed being damaged.
            enemies = [b for b in enemies if b['hp'] > 0 or b['handle'] == self.combat_handle]
            targets = bars or enemies
            active = next((b for b in targets if b['handle'] == self.combat_handle), None)
            if active is not None:
                targets = [active] + [b for b in targets if b is not active]
            self.combat_bars = targets
            self.combat_handle = targets[0]['handle'] if targets else None
            return bars,('Live boss data connected.' if bars else
                         'Live enemy data connected.' if enemies else
                         'Connected — no active boss health bar.')
        except (OSError,ValueError,UnicodeError):
            self.fe=None;self.combat_bars=[];self.combat_handle=None
            self.npc_samples=[];self.npc_status='Waiting for valid game data.'
            return [],'Waiting for valid game UI data.'
