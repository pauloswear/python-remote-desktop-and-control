"""
Raw socket versions of controllee and controller protocols
Ultra-high performance implementations without Twisted overhead
"""
import time
import threading
from mss import mss
import numpy as np
import zlib
import struct
import io
import PIL.Image
from constants import *
import commands
from raw_transport import RawSocketProtocol
import tkinter

def create_raw_controller_protocol():
    """Factory function to create RawControllerProtocol with tkinter root"""
    tk_root = tkinter.Tk()
    # Don't use tksupport for raw sockets - we'll handle the main loop differently
    return RawControllerProtocol(tk_root)

class RawControlleeProtocol(RawSocketProtocol):
    """Ultra-high performance controllee using raw sockets"""
    
    def __init__(self):
        super().__init__()
        self.config = {}
        self.last_screenshot_time = 0
        self.screenshot_interval = 1.0 / VAR_FPS_DEFAULT
        self.screenshot_lock = threading.Lock()
        self.is_processing_screenshot = False
        self.screenshot_thread = None
        
        # Initialize config
        self.set_variable(VAR_SCALE, VAR_SCALE_DEFAULT, False)
        self.set_variable(VAR_MONITOR, VAR_MONITOR_DEFAULT, False)
        self.set_variable(VAR_SHOULD_UPDATE_COMMANDS, VAR_SHOULD_UPDATE_COMMANDS_DEFAULT, False)
        self.set_variable(VAR_FPS, VAR_FPS_DEFAULT, False)
        self.set_variable(VAR_JPEG_QUALITY, VAR_JPEG_QUALITY_DEFAULT, False)
        self.set_variable(VAR_USE_NUMPY, VAR_USE_NUMPY_DEFAULT, False)
        self.set_variable(VAR_COMPRESSION_LEVEL, VAR_COMPRESSION_LEVEL_DEFAULT, False)
        
        # Set message handler
        self.set_message_handler(self.message_received)
        
        # Start command processor
        self.commands = commands.Commands(self.config)
        self.commands.start()
        
    def connection_made(self):
        """Called when connection is established"""
        print("Raw controllee connected")
        self.print_config()
        
        # Start ultra-aggressive screenshot loop
        self.screenshot_thread = threading.Thread(target=self._screenshot_loop, daemon=True)
        self.screenshot_thread.start()
    
    def _screenshot_loop(self):
        """Ultra-high performance screenshot loop"""
        while self.running:
            try:
                current_time = time.time()
                
                # Ultra-aggressive timing
                if current_time - self.last_screenshot_time >= self.screenshot_interval:
                    with self.screenshot_lock:
                        if not self.is_processing_screenshot:
                            self.is_processing_screenshot = True
                            self.last_screenshot_time = current_time
                            
                            try:
                                # Smart method selection
                                fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
                                use_numpy = self.config.get(VAR_USE_NUMPY, VAR_USE_NUMPY_DEFAULT)
                                scale = self.config.get(VAR_SCALE, VAR_SCALE_DEFAULT)
                                
                                if use_numpy and scale <= 0.5 and fps_target >= 90:
                                    self.send_screenshot_numpy()
                                else:
                                    self.send_screenshot_jpeg()
                            finally:
                                self.is_processing_screenshot = False
                
                # Ultra-short sleep for maximum responsiveness
                time.sleep(0.0001)  # 0.1ms
                
            except Exception as e:
                print(f"Screenshot loop error: {e}")
                time.sleep(0.001)
    
    def send_screenshot_numpy(self):
        """Ultra-fast numpy implementation"""
        with mss() as sct:
            monitor_idx = min(self.config[VAR_MONITOR], len(sct.monitors) - 1)
            ss = sct.grab(sct.monitors[monitor_idx])
            
            # Direct numpy conversion
            img_array = np.frombuffer(ss.bgra, dtype=np.uint8).reshape((ss.height, ss.width, 4))
            rgb_array = img_array[:, :, [2, 1, 0]]  # BGR to RGB
            
            # Ultra-fast downsampling
            if self.config[VAR_SCALE] < 1:
                step = max(1, int(1/self.config[VAR_SCALE]))
                rgb_array = rgb_array[::step, ::step]
            
            # Adaptive compression
            fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
            header = struct.pack('<III', rgb_array.shape[0], rgb_array.shape[1], rgb_array.shape[2])
            
            if fps_target > 120:
                # Raw mode for extreme FPS
                message_data = b'NUMPY' + header + rgb_array.tobytes()
            else:
                # Compressed mode
                compression_level = self.config.get(VAR_COMPRESSION_LEVEL, VAR_COMPRESSION_LEVEL_DEFAULT)
                compressed_data = zlib.compress(rgb_array.tobytes(), compression_level)
                message_data = b'NUMPY' + header + compressed_data
            
            self.write_message(message_data)
    
    def send_screenshot_jpeg(self):
        """Ultra-optimized JPEG implementation"""
        with io.BytesIO() as output:
            with mss() as sct:
                monitor_idx = min(self.config[VAR_MONITOR], len(sct.monitors) - 1)
                ss = sct.grab(sct.monitors[monitor_idx])
                
                # Fast PIL conversion
                ss = PIL.Image.frombytes('RGB', ss.size, ss.bgra, 'raw', 'BGRX')
                
                # Fast scaling
                if self.config[VAR_SCALE] < 1:
                    new_size = (int(ss.size[0] * self.config[VAR_SCALE]),
                               int(ss.size[1] * self.config[VAR_SCALE]))
                    ss = ss.resize(new_size, PIL.Image.NEAREST)
                
                # Adaptive quality for FPS
                fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
                if fps_target >= 120:
                    quality = 10  # Extreme speed
                elif fps_target >= 60:
                    quality = 20  # High speed
                else:
                    quality = self.config.get(VAR_JPEG_QUALITY, VAR_JPEG_QUALITY_DEFAULT)
                
                ss.save(output, format="JPEG", quality=quality, optimize=False)
                self.write_message(output.getvalue())
    
    def message_received(self, data: bytes):
        """Handle received messages"""
        try:
            decoded = data.decode('ascii')
            
            if decoded == COMMAND_SEND_SCREENSHOT:
                pass  # Screenshots are sent automatically
            elif decoded.startswith(COMMAND_SET_VAR):
                command_info = __import__('json').loads(decoded[len(COMMAND_SET_VAR):])
                self.set_variable(**command_info)
            elif decoded.startswith(COMMAND_NEW_COMMAND):
                command_info = __import__('json').loads(decoded[len(COMMAND_NEW_COMMAND):])
                self.commands.addCommand(*command_info)
        except Exception as e:
            print(f"Message processing error: {e}")
    
    def set_variable(self, variable, value, should_print=True):
        """Set configuration variable"""
        self.config[variable] = value
        
        # Update FPS interval
        if variable == VAR_FPS and value > 0:
            self.screenshot_interval = 1.0 / value
            
        if should_print:
            self.print_config()
    
    def print_config(self):
        """Print current configuration"""
        print("Raw Controllee Config:", self.config)
    
    def stop(self):
        """Stop the protocol"""
        super().stop()
        if self.commands:
            self.commands.shouldRun = False


class RawControllerProtocol(RawSocketProtocol):
    """Ultra-high performance controller using raw sockets"""
    
    def __init__(self, tk_root):
        super().__init__()
        self.tk_root = tk_root
        self.last_received_time = time.time()
        
        # Set message handler
        self.set_message_handler(self.message_received)
        
        # Initialize UI (adapted from original controller.py)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the UI similar to original controller"""
        import tkinter
        
        print("Raw Controller: Setting up UI")
        self.root = tkinter.Toplevel(self.tk_root)
        self.root.state('zoomed')
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_clicked)
        
        frame = tkinter.Frame(self.root)
        frame.pack()
        
        # Monitor control
        tkinter.Label(frame, text='Monitor:').pack(side=tkinter.LEFT)
        self.mon_scale = tkinter.Scale(frame, from_=0, to=4, orient=tkinter.HORIZONTAL, 
                                      command=self.change_monitor)
        self.mon_scale.pack(side=tkinter.LEFT)
        self.mon_scale.set(VAR_MONITOR_DEFAULT)
        
        # Scale control
        tkinter.Label(frame, text='Scale:').pack(side=tkinter.LEFT)
        self.scale_scale = tkinter.Scale(frame, from_=0.1, to=1, orient=tkinter.HORIZONTAL, 
                                        resolution=0.1, command=self.change_scale)
        self.scale_scale.pack(side=tkinter.LEFT)
        self.scale_scale.set(VAR_SCALE_DEFAULT)
        
        # FPS control
        tkinter.Label(frame, text='FPS:').pack(side=tkinter.LEFT)
        self.fps_scale = tkinter.Scale(frame, from_=30, to=144, orient=tkinter.HORIZONTAL, 
                                      command=self.change_fps)
        self.fps_scale.pack(side=tkinter.LEFT)
        self.fps_scale.set(VAR_FPS_DEFAULT)
        
        # Quality control
        tkinter.Label(frame, text='Quality:').pack(side=tkinter.LEFT)
        self.quality_scale = tkinter.Scale(frame, from_=10, to=95, orient=tkinter.HORIZONTAL, 
                                          command=self.change_quality)
        self.quality_scale.pack(side=tkinter.LEFT)
        self.quality_scale.set(VAR_JPEG_QUALITY_DEFAULT)
        
        # Update commands checkbox
        self.update_var = tkinter.BooleanVar(self.root, VAR_SHOULD_UPDATE_COMMANDS_DEFAULT)
        update_check = tkinter.Checkbutton(frame, text='Update commands', 
                                          command=self.change_update_commands, 
                                          variable=self.update_var)
        update_check.pack(side=tkinter.LEFT)
        
        # FPS label
        tkinter.Label(frame, text='FPS:').pack(side=tkinter.LEFT)
        self.fps_label = tkinter.Label(frame, text='?')
        self.fps_label.pack(side=tkinter.LEFT)
        
        # Image label
        self.label = tkinter.Label(self.root)
        self.label.pack(fill=tkinter.BOTH, expand=True)
        
        # Bind events
        self.root.bind('<Key>', self.on_key_down)
        self.root.bind('<KeyRelease>', self.on_key_up)
        self.label.bind('<Button>', self.on_mouse_down)
        self.label.bind('<ButtonRelease>', self.on_mouse_up)
        self.label.bind('<MouseWheel>', self.on_mouse_wheel)
        
        self.root.focus_set()
    
    def connection_made(self):
        """Called when connection is established"""
        print("Raw controller connected")
        # Request first screenshot
        self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
    
    # Control methods
    def change_monitor(self, new_monitor: str):
        self.set_value(VAR_MONITOR, int(new_monitor))
    
    def change_scale(self, new_scale: str):
        self.set_value(VAR_SCALE, float(new_scale))
    
    def change_fps(self, new_fps: str):
        self.set_value(VAR_FPS, int(new_fps))
    
    def change_quality(self, new_quality: str):
        self.set_value(VAR_JPEG_QUALITY, int(new_quality))
    
    def change_update_commands(self):
        self.set_value(VAR_SHOULD_UPDATE_COMMANDS, self.update_var.get())
    
    def set_value(self, variable, value):
        import json
        to_send = COMMAND_SET_VAR.encode('ascii')
        to_send += json.dumps({
            'variable': variable,
            'value': value
        }).encode('ascii')
        self.write_message(to_send)
    
    def send_command(self, command_name, *args):
        import json
        to_send = COMMAND_NEW_COMMAND.encode('ascii')
        to_send += json.dumps([command_name, *args]).encode('ascii')
        self.write_message(to_send)
    
    def get_local_position(self, x, y):
        label_size = self.get_label_size()
        return (x / label_size[0], y / label_size[1])
    
    def get_label_size(self):
        return (self.label.winfo_width(), self.label.winfo_height())
    
    def send_mouse_event(self, event, is_down: bool):
        location = self.get_local_position(event.x, event.y)
        self.send_command('MoveMouse', location[0], location[1])
        self.send_command('MouseInput', event.num == 1, is_down)
    
    def on_mouse_down(self, event):
        self.send_mouse_event(event, True)
    
    def on_mouse_up(self, event):
        self.send_mouse_event(event, False)
    
    def on_mouse_wheel(self, event):
        location = self.get_local_position(event.x, event.y)
        scroll_direction = 1 if event.delta > 0 else -1
        scroll_amount = abs(event.delta) // 120
        self.send_command('ScrollMouse', location[0], location[1], scroll_direction, scroll_amount)
    
    def send_key_event(self, event, is_down: bool):
        self.send_command('KeyboardInput', event.keycode, is_down)
    
    def on_key_down(self, event):
        self.send_key_event(event, True)
    
    def on_key_up(self, event):
        self.send_key_event(event, False)
    
    def on_close_clicked(self):
        self.stop()
        if hasattr(self.tk_root, 'quit'):
            self.tk_root.quit()
    
    def message_received(self, data: bytes):
        """Handle received screenshots"""
        try:
            current_time = time.time()
            
            # Process image data (numpy or JPEG)
            if data.startswith(b'NUMPY'):
                self.process_numpy_data(data[5:])
            else:
                self.process_jpeg_data(data)
            
            # Calculate and display FPS
            if hasattr(self, 'last_received_time') and hasattr(self, 'fps_label'):
                fps = 1.0 / (current_time - self.last_received_time)
                self.fps_label['text'] = f'{fps:.1f}'
            
            self.last_received_time = current_time
            
            # Request next screenshot immediately
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
            
        except Exception as e:
            print(f"Controller message error: {e}")
            # Still request next screenshot
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
    
    def process_numpy_data(self, data: bytes):
        """Process numpy data"""
        try:
            import PIL.Image
            from PIL import ImageTk
            
            header_size = struct.calcsize('<III')
            if len(data) < header_size:
                return
            
            height, width, channels = struct.unpack('<III', data[:header_size])
            payload_data = data[header_size:]
            
            expected_size = height * width * channels
            
            if len(payload_data) == expected_size:
                array_bytes = payload_data
            else:
                array_bytes = zlib.decompress(payload_data)
            
            # Reconstruct numpy array
            img_array = np.frombuffer(array_bytes, dtype=np.uint8).reshape((height, width, channels))
            
            # Convert to PIL and display
            img = PIL.Image.fromarray(img_array, 'RGB')
            new_size = self.get_label_size()
            if new_size[0] > 0 and new_size[1] > 0:
                img = img.resize(new_size, PIL.Image.NEAREST)
                self.current_image = ImageTk.PhotoImage(img)
                self.label.configure(image=self.current_image)
            
        except Exception as e:
            print(f"Numpy processing error: {e}")
    
    def process_jpeg_data(self, data: bytes):
        """Process JPEG data"""
        try:
            import PIL.Image
            from PIL import ImageTk
            
            new_size = self.get_label_size()
            if new_size[0] > 0 and new_size[1] > 0:
                img = PIL.Image.open(io.BytesIO(data))
                img = img.resize(new_size, PIL.Image.NEAREST)
                self.current_image = ImageTk.PhotoImage(img)
                self.label.configure(image=self.current_image)
                
        except Exception as e:
            print(f"JPEG processing error: {e}")