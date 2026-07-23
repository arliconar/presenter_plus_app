import tkinter as tk
from tkinter import ttk, scrolledtext
import hid
import threading
import time
import keyboard

class PresenterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Microsoft Presenter+ Raw HID Monitor")
        self.root.geometry("800x600")
        
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # UI Setup
        self.top_frame = ttk.Frame(root, padding=10)
        self.top_frame.pack(fill=tk.X)
        
        ttk.Label(self.top_frame, text="Dispositivo HID:").pack(side=tk.LEFT, padx=5)
        
        self.device_combo = ttk.Combobox(self.top_frame, width=50, state="readonly")
        self.device_combo.pack(side=tk.LEFT, padx=5)
        
        self.connect_btn = ttk.Button(self.top_frame, text="Conectar", command=self.toggle_connection)
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        self.clear_btn = ttk.Button(self.top_frame, text="Limpiar", command=self.clear_log)
        self.clear_btn.pack(side=tk.RIGHT, padx=5)
        
        self.log_area = scrolledtext.ScrolledText(root, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 11))
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.status_var = tk.StringVar()
        self.status_var.set("Desconectado")
        self.status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.devices = []
        self.active_devices = [] # Lista de (device, thread, stop_event)
        self.is_connected = False
        
        self.refresh_devices()
        
    def log(self, msg):
        self.log_area.insert(tk.END, f"{msg}\n")
        self.log_area.see(tk.END)
        
    def clear_log(self):
        self.log_area.delete('1.0', tk.END)
        
    def refresh_devices(self):
        self.devices = hid.enumerate()
        
        # Agrupar por VendorID y ProductID para mostrar
        grouped = {}
        for d in self.devices:
            key = (d['vendor_id'], d['product_id'])
            if key not in grouped:
                grouped[key] = {
                    'name': d.get('product_string', 'Desconocido'),
                    'manufacturer': d.get('manufacturer_string', ''),
                    'paths': []
                }
            grouped[key]['paths'].append(d['path'])
            
        self.grouped_devices = grouped
        
        combo_values = []
        target_index = 0
        
        for idx, (key, info) in enumerate(self.grouped_devices.items()):
            vid, pid = key
            name = f"{info['manufacturer']} {info['name']} [VID:{vid:04X} PID:{pid:04X}] ({len(info['paths'])} interfaces)"
            combo_values.append(name)
            
            # Auto-select Presenter+ if found
            if "Presenter" in info['name'] or "Microsoft" in info['manufacturer']:
                target_index = idx
                
        self.device_combo['values'] = combo_values
        if combo_values:
            self.device_combo.current(target_index)
            
    def toggle_connection(self):
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()
            
    def connect(self):
        idx = self.device_combo.current()
        if idx < 0:
            return
            
        key = list(self.grouped_devices.keys())[idx]
        info = self.grouped_devices[key]
        
        self.log(f"Conectando a {info['name']}...")
        self.log(f"Se encontraron {len(info['paths'])} interfaces HID internas. Abriendo todas...")
        
        success_count = 0
        
        for path in info['paths']:
            try:
                # Abrimos cada interfaz
                dev = hid.device()
                dev.open_path(path)
                stop_event = threading.Event()
                
                t = threading.Thread(target=self.read_loop, args=(dev, path, stop_event))
                t.daemon = True
                t.start()
                
                self.active_devices.append((dev, t, stop_event))
                success_count += 1
                self.log(f"  ✓ Interfaz abierta: {path}")
            except Exception as e:
                self.log(f"  ❌ No se pudo abrir interfaz {path}: {e}")
                
        if success_count > 0:
            self.is_connected = True
            self.connect_btn.config(text="Desconectar")
            self.status_var.set(f"Conectado a {success_count} interfaces.")
            self.device_combo.config(state="disabled")
        else:
            self.log("⚠️ No se pudo abrir ninguna interfaz. (Intenta ejecutar como Administrador).")
            
    def disconnect(self):
        self.log("Desconectando...")
        for dev, t, stop_event in self.active_devices:
            stop_event.set()
            # el thread se cerrará
            
        self.active_devices = []
        self.is_connected = False
        self.connect_btn.config(text="Conectar")
        self.device_combo.config(state="readonly")
        self.status_var.set("Desconectado")
        
    def read_loop(self, dev, path, stop_event):
        # Establecemos el modo no bloqueante
        dev.set_nonblocking(1)
        
        while not stop_event.is_set():
            try:
                data = dev.read(64)
                if data:
                    hex_data = " ".join([f"{b:02X}" for b in data])
                    
                    if hex_data.startswith("04 3F 01"):
                        # Simular el atajo global de Mute en Teams
                        keyboard.send("ctrl+shift+m")
                        self.root.after(0, self.log, f"🎙️ [ACCIÓN] Silenciando Teams (Ctrl+Shift+M)")
                    
                    # Ejecutar en el hilo principal de UI
                    self.root.after(0, self.log, f"📡 Datos RAW: {hex_data}")
                else:
                    time.sleep(0.01) # Pequeña pausa para no saturar CPU
            except Exception as e:
                self.root.after(0, self.log, f"❌ Error leyendo de {path}: {e}")
                break
                
        try:
            dev.close()
        except:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = PresenterApp(root)
    root.mainloop()
