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
        
        # Adaptive quality control
        self.network_stats = {
            'rtt_samples': [],
            'fps_history': [],
            'last_quality_adjustment': 0,
            'current_quality_offset': 0
        }
        
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
                
                # Minimal sleep for ultra-low latency
                time.sleep(0.001)  # 1ms for maximum responsiveness
                
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
        """Tile-based JPEG implementation with delta encoding"""
        with mss() as sct:
            monitor_idx = min(self.config[VAR_MONITOR], len(sct.monitors) - 1)
            ss = sct.grab(sct.monitors[monitor_idx])
            
            # Convert to PIL Image
            img = PIL.Image.frombytes("RGB", (ss.width, ss.height), ss.bgra, "raw", "BGRX")
            
            # Apply scaling
            scale = self.config.get(VAR_SCALE, VAR_SCALE_DEFAULT)
            if scale < 1:
                new_width = int(img.size[0] * scale)
                new_height = int(img.size[1] * scale)
                img = img.resize((new_width, new_height), PIL.Image.LANCZOS)
            
            # Use tile-based delta encoding
            changed_tiles = self._get_changed_tiles(img)
            
            if not changed_tiles:
                # No changes detected, send minimal update
                self.write_message(b'NO_CHANGE')
                return
            
            # Send changed tiles
            self._send_changed_tiles(img, changed_tiles)
    
    def _get_changed_tiles(self, img):
        """Detect which tiles have changed using hash comparison and cache static tiles"""
        width, height = img.size
        changed_tiles = []
        current_time = time.time()
        
        for y in range(0, height, self.tile_size):
            for x in range(0, width, self.tile_size):
                # Define tile bounds
                tile_width = min(self.tile_size, width - x)
                tile_height = min(self.tile_size, height - y)
                
                # Extract tile
                tile = img.crop((x, y, x + tile_width, y + tile_height))
                
                # Create hash for change detection
                tile_hash = hash(tile.tobytes())
                tile_key = (x // self.tile_size, y // self.tile_size)
                
                # Check if tile changed
                if tile_key not in self.last_tiles or self.last_tiles[tile_key] != tile_hash:
                    changed_tiles.append((x, y, tile_width, tile_height, tile_key))
                    self.last_tiles[tile_key] = tile_hash
                    self.tile_timestamps[tile_key] = current_time
                else:
                    # Tile hasn't changed, check if it's become static
                    if tile_key in self.tile_timestamps:
                        time_since_change = current_time - self.tile_timestamps[tile_key]
                        if time_since_change > self.static_tile_threshold:
                            # Mark as static - don't send anymore
                            continue
                    
                    # Still send occasionally to ensure sync
                    if tile_key not in self.tile_timestamps or (current_time - self.tile_timestamps.get(tile_key, 0)) > 30.0:
                        # Send every 30 seconds to maintain sync
                        changed_tiles.append((x, y, tile_width, tile_height, tile_key))
                        self.tile_timestamps[tile_key] = current_time
        
        return changed_tiles
    
    def _send_changed_tiles(self, img, changed_tiles):
        """Send only the changed tiles with optimized encoding"""
        # Adaptive quality based on number of changed tiles and target FPS
        num_changed = len(changed_tiles)
        fps_target = self.config.get(VAR_FPS, VAR_FPS_DEFAULT)
        
        # Calculate change ratio for adaptive quality
        total_tiles = ((img.size[0] + self.tile_size - 1) // self.tile_size) * ((img.size[1] + self.tile_size - 1) // self.tile_size)
        change_ratio = num_changed / max(total_tiles, 1)
        
        # Adaptive quality: higher for fewer changes, lower for high FPS targets
        if fps_target >= 120:
            base_quality = 20  # Very low quality for max speed
        elif fps_target >= 60:
            base_quality = 35  # Low quality for high speed
        else:
            base_quality = 60  # Balanced quality
        
        # Adjust quality based on change ratio
        if change_ratio < 0.05:  # Very few changes
            quality = min(95, base_quality + 30)  # Higher quality for better compression
        elif change_ratio < 0.2:  # Moderate changes
            quality = base_quality
        else:  # Many changes
            quality = max(10, base_quality - 15)  # Lower quality for speed
        
        # Send tile update header with quality info
        header = struct.pack('<III', len(changed_tiles), quality, int(fps_target))
        self.write_message(b'TILES' + header)
        
        # Send each changed tile with optimized encoding
        for x, y, tile_width, tile_height, tile_key in changed_tiles:
            tile = img.crop((x, y, x + tile_width, y + tile_height))
            
            # Ultra-fast encoding optimized for tiles
            with io.BytesIO() as output:
                tile.save(output, format="JPEG", 
                         quality=quality, 
                         optimize=False,  # Skip optimization for speed
                         progressive=False,  # Disable progressive for speed
                         subsampling=2 if quality < 50 else 0)  # Aggressive subsampling for low quality
                
                tile_data = output.getvalue()
            
            # Send tile header + data
            tile_header = struct.pack('<IIII', x, y, tile_width, tile_height)
            self.write_message(tile_header + tile_data)
    
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
            elif decoded.startswith("NET_FEEDBACK:"):
                # Process network feedback for adaptive quality
                parts = decoded.split(":")
                if len(parts) >= 3:
                    quality_adjustment = int(parts[1])
                    current_fps = float(parts[2])
                    self._adjust_quality_based_on_feedback(quality_adjustment, current_fps)
        except Exception as e:
            print(f"Message processing error: {e}")
    
    def _adjust_quality_based_on_feedback(self, quality_adjustment, current_fps):
        """Adjust quality based on network feedback"""
        # Apply quality adjustment with bounds
        self.network_stats['current_quality_offset'] += quality_adjustment
        self.network_stats['current_quality_offset'] = max(-50, min(50, self.network_stats['current_quality_offset']))
        
        # Store FPS history for trend analysis
        self.network_stats['fps_history'].append(current_fps)
        if len(self.network_stats['fps_history']) > 10:
            self.network_stats['fps_history'].pop(0)
        
        # Adjust tile size based on performance
        avg_fps = sum(self.network_stats['fps_history']) / len(self.network_stats['fps_history']) if self.network_stats['fps_history'] else current_fps
        
        if avg_fps < 30 and self.tile_size > 32:
            self.tile_size = max(32, self.tile_size // 2)  # Smaller tiles for better granularity
            print(f"Reduced tile size to {self.tile_size} for better performance")
        elif avg_fps > 50 and self.tile_size < 128:
            self.tile_size = min(128, self.tile_size * 2)  # Larger tiles for better compression
            print(f"Increased tile size to {self.tile_size} for better compression")
    
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
        
        # Tile management
        self.tile_cache = {}  # Cache of received tiles
        self.full_image = None  # Reconstructed full image
        self.image_size = None  # Size of the full image
        
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
        
        # Anti-flicker configurations
        self.root.configure(bg='black')  # Set background to black to avoid white flash
        
        frame = tkinter.Frame(self.root, bg='black')  # Black background for frame too
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
        
        # Image label with anti-flicker settings
        self.label = tkinter.Label(self.root, bg='black', highlightthickness=0, bd=0)
        self.label.pack(fill=tkinter.BOTH, expand=True)
        
        # Initialize with a black image to prevent white flash
        self.current_image = None
        self.create_initial_black_image()
        
        # Bind events
        self.root.bind('<Key>', self.on_key_down)
        self.root.bind('<KeyRelease>', self.on_key_up)
        self.label.bind('<Button>', self.on_mouse_down)
        self.label.bind('<ButtonRelease>', self.on_mouse_up)
        self.label.bind('<MouseWheel>', self.on_mouse_wheel)
        
        self.root.focus_set()
    
    def create_initial_black_image(self):
        """Create initial black image to prevent white flash"""
        try:
            from PIL import Image, ImageTk
            # Create a small black image
            black_img = Image.new('RGB', (100, 100), color='black')
            self.current_image = ImageTk.PhotoImage(black_img)
            self.label.configure(image=self.current_image)
        except Exception as e:
            print(f"Error creating initial black image: {e}")
    
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
        """Handle received screenshots and tiles"""
        try:
            current_time = time.time()
            
            if data == b'NO_CHANGE':
                # No changes, just update FPS
                pass
            elif data.startswith(b'TILES'):
                # Tile-based update
                self._process_tiles(data[5:])
            else:
                # Legacy full image
                self.process_jpeg_data(data)
            
            # Calculate and display FPS
            if hasattr(self, 'last_received_time') and hasattr(self, 'fps_label'):
                fps = 1.0 / (current_time - self.last_received_time)
                self.fps_label['text'] = f'{fps:.1f}'
                
                # Send network stats back to controllee for adaptive quality
                self._send_network_feedback(fps)
            
            self.last_received_time = current_time
            
            # Request next screenshot immediately
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
            
        except Exception as e:
            print(f"Controller message error: {e}")
            # Still request next screenshot
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
    
    def _send_network_feedback(self, current_fps):
        """Send network performance feedback to controllee"""
        # Simple adaptive quality: if FPS is low, request lower quality
        target_fps = self.fps_scale.get() if hasattr(self, 'fps_scale') else VAR_FPS_DEFAULT
        
        if current_fps < target_fps * 0.8:  # FPS is 20% below target
            quality_adjustment = -10  # Reduce quality
        elif current_fps > target_fps * 1.1:  # FPS is 10% above target
            quality_adjustment = 5  # Can increase quality slightly
        else:
            quality_adjustment = 0  # Keep current quality
        
        # Send feedback
        feedback = f"NET_FEEDBACK:{quality_adjustment}:{current_fps:.1f}"
        self.write_message(feedback.encode('ascii'))
    
    def process_numpy_data(self, data: bytes):
        """Process numpy data with anti-flicker optimization"""
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
            
            # Convert to PIL and display with anti-flicker
            img = PIL.Image.fromarray(img_array, 'RGB')
            new_size = self.get_label_size()
            if new_size[0] > 0 and new_size[1] > 0:
                img = img.resize(new_size, PIL.Image.NEAREST)
                
                # Anti-flicker: only update if we have a valid image
                new_image = ImageTk.PhotoImage(img)
                
                # Use after_idle to prevent flicker
                self.tk_root.after_idle(lambda: self.update_image_safe(new_image))
            
        except Exception as e:
            print(f"Numpy processing error: {e}")
    
    def _process_tiles(self, data: bytes):
        """Process tile-based updates"""
        try:
            import PIL.Image
            from PIL import ImageTk
            
            # Parse header
            if len(data) < 8:
                return
            num_tiles, quality = struct.unpack('<II', data[:8])
            data = data[8:]
            
            # Process tiles
            tiles_processed = 0
            while tiles_processed < num_tiles and len(data) >= 16:
                # Parse tile header
                tile_header = data[:16]
                x, y, tile_width, tile_height = struct.unpack('<IIII', tile_header)
                data = data[16:]
                
                # Find JPEG data end (look for next tile header or end)
                jpeg_end = len(data)
                if tiles_processed < num_tiles - 1:
                    # Look for next tile header (16 bytes of 4 ints)
                    for i in range(16, len(data) - 16):
                        if len(data) > i + 16:
                            try:
                                # Check if this looks like coordinates
                                test_x, test_y, test_w, test_h = struct.unpack('<IIII', data[i:i+16])
                                if 0 <= test_x <= 10000 and 0 <= test_y <= 10000 and 1 <= test_w <= 200 and 1 <= test_h <= 200:
                                    jpeg_end = i
                                    break
                            except:
                                continue
                
                jpeg_data = data[:jpeg_end]
                data = data[jpeg_end:]
                
                # Decode tile
                try:
                    tile_img = PIL.Image.open(io.BytesIO(jpeg_data))
                    
                    # Cache tile
                    tile_key = (x, y)
                    self.tile_cache[tile_key] = tile_img
                    
                    # Update image size if needed
                    if self.image_size is None:
                        # Estimate full image size (this is approximate)
                        self.image_size = (1920, 1080)  # Default, will be updated
                    
                    tiles_processed += 1
                    
                except Exception as e:
                    print(f"Tile decode error: {e}")
                    continue
            
            # Reconstruct full image from tiles
            self._reconstruct_image()
            
        except Exception as e:
            print(f"Tile processing error: {e}")
    
    def _reconstruct_image(self):
        """Reconstruct full image from cached tiles"""
        if not self.tile_cache or not self.image_size:
            return
        
        try:
            import PIL.Image
            from PIL import ImageTk
            
            # Create full image
            full_img = PIL.Image.new('RGB', self.image_size, (0, 0, 0))
            
            # Paste tiles
            for (x, y), tile in self.tile_cache.items():
                # Ensure tile fits
                if x + tile.size[0] <= self.image_size[0] and y + tile.size[1] <= self.image_size[1]:
                    full_img.paste(tile, (x, y))
            
            # Resize to fit display
            new_size = self.get_label_size()
            if new_size[0] > 0 and new_size[1] > 0:
                full_img = full_img.resize(new_size, PIL.Image.NEAREST)
                
                # Update display
                new_image = ImageTk.PhotoImage(full_img)
                self.tk_root.after_idle(lambda: self.update_image_safe(new_image))
                
        except Exception as e:
            print(f"Image reconstruction error: {e}")
    
    def update_image_safe(self, new_image):
        """Safely update image to prevent flicker"""
        try:
            if new_image and hasattr(self, 'label'):
                # Keep reference to prevent garbage collection
                self.current_image = new_image
                self.label.configure(image=self.current_image)
                # Force update without flickering
                self.label.update_idletasks()
        except Exception as e:
            print(f"Safe image update error: {e}")