import pystray
from PIL import Image, ImageDraw
import hid
import threading
import time
import keyboard
import collections
import os
import json

class PresenterDaemon:
    def __init__(self):
        self.log_history = collections.deque(maxlen=100)
        self.log("Iniciando Presenter+ Daemon...")
        
        self.config_path = os.path.expanduser('~/.presenter_plus_config.json')
        
        # State
        self.is_running = True
        self.icon = None
        
        # Selected target device: None means auto-connect to Microsoft/Presenter+
        self.selected_vid_pid = self.load_config()
        self.reconnect_requested = False
        self.search_enabled = True
        
        self.active_devices = [] # list of hid.device objects
        self.devices_info = {} # dict mapping (vid, pid) -> info
        
        # Threads
        self.stop_event = threading.Event()
        self.hid_thread = None

    def create_image(self):
        # A simple green icon indicating it's active
        image = Image.new('RGB', (64, 64), color=(0, 0, 0))
        d = ImageDraw.Draw(image)
        d.rectangle((16, 16, 48, 48), fill=(0, 255, 0))
        return image
        
    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {msg}"
        self.log_history.append(formatted)
        print(formatted)

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    vid_pid = data.get('selected_vid_pid')
                    if vid_pid:
                        return tuple(vid_pid)
            except Exception as e:
                self.log(f"Error cargando configuración: {e}")
        return None

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({'selected_vid_pid': self.selected_vid_pid}, f)
        except Exception as e:
            self.log(f"Error guardando configuración: {e}")

    def enumerate_grouped_devices(self):
        devices = hid.enumerate()
        grouped = {}
        for d in devices:
            key = (d['vendor_id'], d['product_id'])
            if key not in grouped:
                grouped[key] = {
                    'name': d.get('product_string', 'Desconocido'),
                    'manufacturer': d.get('manufacturer_string', ''),
                    'paths': []
                }
            grouped[key]['paths'].append(d['path'])
        return grouped

    def hid_loop(self):
        while not self.stop_event.is_set():
            if not self.search_enabled:
                self.stop_event.wait(2.0)
                continue
                
            # Update devices_info for the menu
            self.devices_info = self.enumerate_grouped_devices()
            
            # Decide what to connect to
            target_paths = []
            
            if self.selected_vid_pid is not None:
                # User manually selected a device
                info = self.devices_info.get(self.selected_vid_pid)
                if info:
                    target_paths = info['paths']
            else:
                # Auto-select Presenter+ / Microsoft
                for key, info in self.devices_info.items():
                    if "Presenter" in info['name'] or "Microsoft" in info['manufacturer']:
                        target_paths.extend(info['paths'])
            
            if not target_paths:
                # No suitable devices found
                self.stop_event.wait(3.0)
                continue
                
            # Try to connect to all interfaces of the target device
            for p in target_paths:
                try:
                    dev = hid.device()
                    dev.open_path(p)
                    dev.set_nonblocking(1)
                    self.active_devices.append(dev)
                    self.log(f"Interfaz conectada: {p}")
                except Exception as e:
                    pass
                    
            if not self.active_devices:
                self.log("Dispositivo encontrado pero no se pudo abrir (Posible problema de permisos).")
                self.stop_event.wait(3.0)
                continue
                
            self.log(f"Conectado a {len(self.active_devices)} interfaces.")
            
            # Read loop
            try:
                while not self.stop_event.is_set():
                    if self.reconnect_requested:
                        self.reconnect_requested = False
                        break
                        
                    if not self.search_enabled:
                        break

                    all_empty = True
                    active_devs_next = []
                    
                    for dev in self.active_devices:
                        data = []
                        try:
                            data = dev.read(64)
                            active_devs_next.append(dev)
                        except:
                            try:
                                dev.close()
                            except:
                                pass
                            continue
                            
                        if data:
                            all_empty = False
                            hex_data = " ".join([f"{b:02X}" for b in data])
                            
                            # Check Presenter+ Mute toggle code
                            if hex_data.startswith("04 3F 01"):
                                keyboard.send("ctrl+shift+m")
                                self.log(f"🎙️ [ACCIÓN] Silenciando Teams (Ctrl+Shift+M)")
                                
                    self.active_devices = active_devs_next
                    
                    if not self.active_devices:
                        self.log("Todas las interfaces se desconectaron. Reconectando...")
                        break
                                
                    if all_empty:
                        time.sleep(0.02)
            except Exception as e:
                self.log(f"Error inesperado: {e}")
            finally:
                for dev in self.active_devices:
                    try:
                        dev.close()
                    except:
                        pass
                self.active_devices = []
                
            # Wait a bit before retry
            self.stop_event.wait(2.0)

    def on_view_logs(self, icon, item):
        log_file = "presenter_logs.txt"
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_history))
                f.write("\n\n-- (Mostrando los últimos 100 eventos) --\n")
            os.startfile(log_file)
        except Exception as e:
            self.log(f"Error abriendo logs: {e}")

    def on_exit(self, icon, item):
        self.log("Saliendo...")
        self.stop_event.set()
        if self.icon:
            self.icon.stop()
            
    def set_device(self, vid_pid):
        self.selected_vid_pid = vid_pid
        if vid_pid is None:
            self.log("Selección: Automático (Presenter+/Microsoft)")
        else:
            self.log(f"Selección manual: VID:{vid_pid[0]:04X} PID:{vid_pid[1]:04X}")
        self.save_config()
        self.reconnect_requested = True

    def get_device_menu(self):
        items = []
        
        items.append(pystray.MenuItem(
            "Auto (Presenter+/Microsoft)",
            lambda icon, item: self.set_device(None),
            checked=lambda item: self.selected_vid_pid is None,
            radio=True
        ))
        
        for key, info in list(self.devices_info.items()):
            vid, pid = key
            name = f"{info['manufacturer']} {info['name']} [VID:{vid:04X} PID:{pid:04X}]"
            if len(name) > 40:
                name = name[:37] + "..."
                
            def make_cb(k):
                return lambda icon, item: self.set_device(k)
                
            def make_checked(k):
                return lambda item: self.selected_vid_pid == k
                
            items.append(pystray.MenuItem(
                name,
                make_cb(key),
                checked=make_checked(key),
                radio=True
            ))
            
        return items

    def toggle_search(self, icon, item):
        self.search_enabled = not self.search_enabled
        if self.search_enabled:
            self.log("Búsqueda de dispositivos ACTIVADA.")
        else:
            self.log("Búsqueda de dispositivos DESACTIVADA.")
        self.reconnect_requested = True

    def run(self):
        # Popule the first device list immediately so menu isn't empty if opened fast
        self.devices_info = self.enumerate_grouped_devices()
        
        self.hid_thread = threading.Thread(target=self.hid_loop, daemon=True)
        self.hid_thread.start()
        
        menu = pystray.Menu(
            pystray.MenuItem("Búsqueda Activa", self.toggle_search, checked=lambda item: self.search_enabled),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ver Logs", self.on_view_logs),
            pystray.MenuItem("Dispositivo", pystray.Menu(lambda: self.get_device_menu())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self.on_exit)
        )
        
        self.icon = pystray.Icon("PresenterPlus", self.create_image(), "Presenter+", menu)
        self.icon.run()

if __name__ == "__main__":
    daemon = PresenterDaemon()
    daemon.run()
