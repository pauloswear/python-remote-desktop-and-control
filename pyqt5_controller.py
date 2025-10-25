"""
PyQt5-based controller implementation for better performance and modern UI
"""
import sys
import time
import struct
import zlib
import io
import json
import queue
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                           QWidget, QLabel, QSlider, QCheckBox, QPushButton)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt5.QtGui import QPixmap, QImage, QPainter
from PIL import Image, ImageTk
import numpy as np
from constants import *
from raw_transport import RawSocketProtocol

class PyQt5ControllerProtocol(QObject):
    """Ultra-modern PyQt5-based controller with superior performance"""
    
    # Signals for thread-safe GUI updates
    image_received = pyqtSignal(bytes)
    fps_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        
        # Create a RawSocketProtocol instance for delegation
        self.protocol = RawSocketProtocol()
        self.protocol.set_message_handler(self.message_received)
        
        self.app = None
        self.window = None
        self.last_received_time = time.time()
        
        # Mouse tracking state
        self.is_dragging = False
        self.drag_button = None
        self.last_mouse_pos = None
        
        # Throttle mouse move commands to improve performance
        self.last_mouse_send_time = 0
        self.mouse_send_interval = 0.01  # 10ms minimum between sends for low latency
        
        # Performance optimization variables
        self.last_image_size = None
        self.cached_pixmap = None
        
        # Tile management for tile-based updates
        self.tile_cache = {}  # Cache of received tiles
        self.image_size = None  # Size of the full image
        
        # Connect signals
        self.image_received.connect(self.update_display)
        self.fps_updated.connect(self.update_fps_label)
        
        # Initialize UI
        self.setup_qt_application()
        
    def setup_qt_application(self):
        """Setup PyQt5 application and main window"""
        if QApplication.instance() is None:
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()
        
        # Performance optimizations for higher FPS
        self.app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
        self.app.setAttribute(Qt.AA_NativeWindows, False)
        self.app.setAttribute(Qt.AA_DontUseNativeMenuBar, True)
            
        self.window = QMainWindow()
        self.window.setWindowTitle("Python Remote Desktop - PyQt5 Controller")
        self.window.setGeometry(100, 100, 1200, 800)
        
        # Disable animations for instant response
        self.window.setAnimated(False)
        self.window.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QLabel { color: white; font-size: 12px; }
            QSlider::groove:horizontal { 
                border: 1px solid #999999; 
                height: 8px; 
                background: #2d2d2d; 
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: #0078d4;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QCheckBox { color: white; }
            QPushButton { 
                background-color: #0078d4; 
                color: white; 
                border: none; 
                padding: 5px 15px; 
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #106ebe; }
        """)
        
        # Main widget and layout
        main_widget = QWidget()
        self.window.setCentralWidget(main_widget)
        
        layout = QVBoxLayout(main_widget)
        
        # Control panel
        self.create_control_panel(layout)
        
        # Image display area
        self.image_label = QLabel()
        self.image_label.setStyleSheet("border: 1px solid #555; background-color: black;")
        self.image_label.setAlignment(Qt.AlignCenter)  # Center the image
        self.image_label.setMinimumSize(800, 600)
        
        # Performance optimizations
        self.image_label.setAttribute(Qt.WA_OpaquePaintEvent)  # Faster painting
        self.image_label.setAttribute(Qt.WA_NoSystemBackground)  # No background clearing
        
        # Enable mouse tracking for real-time movement detection
        self.image_label.setMouseTracking(True)
        
        layout.addWidget(self.image_label)
        
        # Setup mouse and keyboard events
        self.image_label.mousePressEvent = self.mouse_press_event
        self.image_label.mouseReleaseEvent = self.mouse_release_event
        self.image_label.mouseMoveEvent = self.mouse_move_event
        self.image_label.wheelEvent = self.wheel_event
        self.window.keyPressEvent = self.key_press_event
        self.window.keyReleaseEvent = self.key_release_event
        
        # Focus policy for key events
        self.window.setFocusPolicy(Qt.StrongFocus)
        
        # Store original pixmap for resize events
        self.original_pixmap = None
        self.base_image = None  # For delta encoding
        
        # Override resize event
        self.window.resizeEvent = self.window_resize_event
        
    def create_control_panel(self, layout):
        """Create the control panel with sliders and settings"""
        # Control panel container
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        
        # Monitor selection
        control_layout.addWidget(QLabel("Monitor:"))
        self.monitor_slider = QSlider(Qt.Horizontal)
        self.monitor_slider.setRange(0, 4)
        self.monitor_slider.setValue(VAR_MONITOR_DEFAULT)
        self.monitor_slider.valueChanged.connect(self.change_monitor)
        control_layout.addWidget(self.monitor_slider)
        
        # Scale control
        control_layout.addWidget(QLabel("Scale:"))
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(10, 100)  # 0.1 to 1.0 (multiplied by 100)
        self.scale_slider.setValue(int(VAR_SCALE_DEFAULT * 100))
        self.scale_slider.valueChanged.connect(self.change_scale)
        control_layout.addWidget(self.scale_slider)
        
        # FPS control
        control_layout.addWidget(QLabel("FPS:"))
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(30, 240)  # Higher maximum FPS
        self.fps_slider.setValue(VAR_FPS_DEFAULT)
        self.fps_slider.valueChanged.connect(self.change_fps)
        control_layout.addWidget(self.fps_slider)
        
        # Quality control
        control_layout.addWidget(QLabel("Quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 95)
        self.quality_slider.setValue(VAR_JPEG_QUALITY_DEFAULT)
        self.quality_slider.valueChanged.connect(self.change_quality)
        control_layout.addWidget(self.quality_slider)
        
        # Update commands checkbox
        self.update_checkbox = QCheckBox("Update Commands")
        self.update_checkbox.setChecked(VAR_SHOULD_UPDATE_COMMANDS_DEFAULT)
        self.update_checkbox.stateChanged.connect(self.change_update_commands)
        control_layout.addWidget(self.update_checkbox)
        
        # FPS display
        control_layout.addWidget(QLabel("Current FPS:"))
        self.fps_display = QLabel("0.0")
        self.fps_display.setStyleSheet("font-weight: bold; color: #00ff00;")
        control_layout.addWidget(self.fps_display)
        
        layout.addWidget(control_widget)
    
    def change_monitor(self, value):
        self.set_value(VAR_MONITOR, value)
    
    def change_scale(self, value):
        scale_value = value / 100.0  # Convert back to 0.1-1.0 range
        self.set_value(VAR_SCALE, scale_value)
    
    def change_fps(self, value):
        self.set_value(VAR_FPS, value)
    
    def change_quality(self, value):
        self.set_value(VAR_JPEG_QUALITY, value)
    
    def change_update_commands(self, state):
        self.set_value(VAR_SHOULD_UPDATE_COMMANDS, state == Qt.Checked)
    
    def set_value(self, variable, value):
        """Send configuration change to controllee"""
        to_send = COMMAND_SET_VAR.encode('ascii')
        to_send += json.dumps({
            'variable': variable,
            'value': value
        }).encode('ascii')
        self.write_message(to_send)
    
    def send_command(self, command_name, *args):
        """Send command to controllee"""
        to_send = COMMAND_NEW_COMMAND.encode('ascii')
        to_send += json.dumps([command_name, *args]).encode('ascii')
        self.write_message(to_send)
    
    def get_relative_position(self, x, y):
        """Convert screen coordinates to relative position on the actual image"""
        if not self.original_pixmap:
            # Fallback to simple calculation
            rect = self.image_label.geometry()
            return (x / rect.width(), y / rect.height())
        
        # Get the actual displayed pixmap and its position within the label
        current_pixmap = self.image_label.pixmap()
        if not current_pixmap:
            rect = self.image_label.geometry()
            return (x / rect.width(), y / rect.height())
        
        label_rect = self.image_label.rect()
        pixmap_size = current_pixmap.size()
        
        # Calculate the offset where the image starts (due to centering)
        x_offset = (label_rect.width() - pixmap_size.width()) / 2
        y_offset = (label_rect.height() - pixmap_size.height()) / 2
        
        # Adjust coordinates to be relative to the actual image
        image_x = x - x_offset
        image_y = y - y_offset
        
        # Ensure coordinates are within image bounds
        image_x = max(0, min(image_x, pixmap_size.width()))
        image_y = max(0, min(image_y, pixmap_size.height()))
        
        # Convert to relative coordinates (0.0 to 1.0)
        rel_x = image_x / pixmap_size.width() if pixmap_size.width() > 0 else 0
        rel_y = image_y / pixmap_size.height() if pixmap_size.height() > 0 else 0
        
        return (rel_x, rel_y)
    
    def mouse_press_event(self, event):
        """Handle mouse press events"""
        pos = self.get_relative_position(event.x(), event.y())
        
        # Set drag state
        self.is_dragging = True
        self.drag_button = event.button()
        self.last_mouse_pos = pos
        
        # Send mouse move and press
        self.send_command('MoveMouse', pos[0], pos[1])
        self.send_command('MouseInput', event.button() == Qt.LeftButton, True)
    
    def mouse_release_event(self, event):
        """Handle mouse release events"""
        pos = self.get_relative_position(event.x(), event.y())
        
        # Clear drag state
        self.is_dragging = False
        self.drag_button = None
        self.last_mouse_pos = None
        
        # Send mouse move and release
        self.send_command('MoveMouse', pos[0], pos[1])
        self.send_command('MouseInput', event.button() == Qt.LeftButton, False)
    
    def mouse_move_event(self, event):
        """Handle mouse move events - crucial for drag operations"""
        current_time = time.time()
        
        # Throttle mouse move commands to prevent overwhelming the command queue
        if current_time - self.last_mouse_send_time < self.mouse_send_interval:
            return
        
        pos = self.get_relative_position(event.x(), event.y())
        
        # Always send mouse movement for real-time tracking
        self.send_command('MoveMouse', pos[0], pos[1])
        
        # Update last known position and send time
        self.last_mouse_pos = pos
        self.last_mouse_send_time = current_time
    
    def wheel_event(self, event):
        """Handle mouse wheel events"""
        pos = self.get_relative_position(event.x(), event.y())
        delta = event.angleDelta().y()
        scroll_direction = 1 if delta > 0 else -1
        scroll_amount = abs(delta) // 120
        self.send_command('ScrollMouse', pos[0], pos[1], scroll_direction, scroll_amount)
    
    def key_press_event(self, event):
        """Handle key press events"""
        self.send_command('KeyboardInput', event.nativeVirtualKey(), True)
    
    def key_release_event(self, event):
        """Handle key release events"""
        self.send_command('KeyboardInput', event.nativeVirtualKey(), False)
    
    def set_transport(self, transport):
        """Set the transport for communication"""
        self.transport = transport
    
    def connection_made(self):
        """Called when connection is established"""
        print("PyQt5 Controller connected!")
        self.window.show()
        
        # Request first screenshot immediately
        print("Requesting first screenshot...")
        self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
        
        # Start the event loop in a separate thread to avoid blocking
        import threading
        threading.Thread(target=self.run, daemon=True).start()
    
    def message_received(self, data: bytes):
        """Handle received messages (called from transport thread)"""
        try:
            current_time = time.time()
            
            # Calculate and emit FPS
            if hasattr(self, 'last_received_time') and self.last_received_time > 0:
                time_diff = current_time - self.last_received_time
                if time_diff > 0:
                    fps = 1.0 / time_diff
                    self.fps_updated.emit(f"{fps:.1f}")
                    
                    # Send network feedback for adaptive quality
                    self._send_network_feedback(fps)
            
            self.last_received_time = current_time
            
            # Call update_display directly instead of using signals (threading issues)
            self.update_display(data)
            
            # Request next screenshot immediately for maximum FPS
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
            
        except Exception as e:
            print(f"PyQt5 Controller message error: {e}")
    
    def _send_network_feedback(self, current_fps):
        """Send network performance feedback to controllee"""
        # Simple adaptive quality: if FPS is low, request lower quality
        target_fps = self.fps_slider.value() if hasattr(self, 'fps_slider') and self.fps_slider else VAR_FPS_DEFAULT
        
        if current_fps < target_fps * 0.8:  # FPS is 20% below target
            quality_adjustment = -10  # Reduce quality
        elif current_fps > target_fps * 1.1:  # FPS is 10% above target
            quality_adjustment = 5  # Can increase quality slightly
        else:
            quality_adjustment = 0  # Keep current quality
        
        # Send feedback
        feedback = f"NET_FEEDBACK:{quality_adjustment}:{current_fps:.1f}"
        self.write_message(feedback.encode('ascii'))
    
    def update_display(self, data: bytes):
        """Update display with received image data (runs in main thread) - optimized for speed"""
        try:
            # Fast path processing - minimize checks
            if data.startswith(b'NUMPY'):
                self.process_numpy_data(data[5:])
            elif data.startswith(b'TILES'):
                self._process_tiles(data[5:])
            elif data == b'NO_CHANGE':
                # No changes, just keep current image
                pass
            else:
                self.process_jpeg_data(data)
        except Exception as e:
            # Minimize error handling overhead in hot path
            print(f"Display update error: {e}")
            import traceback
            traceback.print_exc()
    
    def process_numpy_data(self, data: bytes):
        """Process numpy array data"""
        try:
            # Read header
            header_size = struct.calcsize('<III')
            if len(data) < header_size:
                return
            
            height, width, channels = struct.unpack('<III', data[:header_size])
            payload_data = data[header_size:]
            
            expected_size = height * width * channels
            
            # Decompress if needed
            if len(payload_data) == expected_size:
                array_bytes = payload_data
            else:
                array_bytes = zlib.decompress(payload_data)
            
            # Convert to numpy array
            img_array = np.frombuffer(array_bytes, dtype=np.uint8).reshape((height, width, channels))
            
            # Handle different channel formats
            if channels == 4:  # BGRA
                # Convert BGRA to RGB
                rgb_array = img_array[:, :, [2, 1, 0]]  # BGR -> RGB
                qimage = QImage(rgb_array.data, width, height, width * 3, QImage.Format_RGB888)
            elif channels == 3:  # BGR or RGB
                # Assume BGR and convert to RGB
                rgb_array = img_array[:, :, [2, 1, 0]]  # BGR -> RGB
                qimage = QImage(rgb_array.data, width, height, width * 3, QImage.Format_RGB888)
            else:
                return
            
            # Convert to QPixmap and display with aspect ratio
            pixmap = QPixmap.fromImage(qimage)
            self.set_pixmap_with_aspect_ratio(pixmap)
            
        except Exception as e:
            print(f"Numpy processing error: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_tiles(self, data: bytes):
        """Process tile-based updates for PyQt5"""
        try:
            print(f"DEBUG: Raw tile data length: {len(data)}")
            
            # Parse header - 3 integers: num_tiles, quality, fps_target
            if len(data) < 12:  # 3 * 4 bytes
                print(f"DEBUG: Tile data too short: {len(data)} bytes")
                return
            num_tiles, quality, fps_target = struct.unpack('<III', data[:12])
            data = data[12:]
            
            print(f"DEBUG: Processing {num_tiles} tiles with quality {quality}, fps_target {fps_target}")
            print(f"DEBUG: Remaining data after header: {len(data)} bytes")
            
            # Process tiles
            tiles_processed = 0
            tile_index = 0
            
            while tile_index < num_tiles and len(data) >= 16:
                print(f"DEBUG: Processing tile {tile_index + 1}/{num_tiles}, data left: {len(data)}")
                
                # Parse tile header
                if len(data) < 16:
                    print(f"DEBUG: Not enough data for tile header: {len(data)}")
                    break
                    
                tile_header = data[:16]
                x, y, tile_width, tile_height = struct.unpack('<IIII', tile_header)
                data = data[16:]
                
                print(f"DEBUG: Tile at ({x},{y}) size ({tile_width},{tile_height})")
                
                # Find JPEG data end (look for next tile header or end)
                jpeg_end = len(data)
                if tile_index < num_tiles - 1:
                    # Look for next tile header (16 bytes of 4 ints)
                    for i in range(max(0, len(data) - 100), len(data) - 16):  # Search last 100 bytes
                        if i >= 0 and len(data) > i + 16:
                            try:
                                # Check if this looks like coordinates
                                test_x, test_y, test_w, test_h = struct.unpack('<IIII', data[i:i+16])
                                if (0 <= test_x <= 10000 and 0 <= test_y <= 10000 and 
                                    1 <= test_w <= 200 and 1 <= test_h <= 200):
                                    jpeg_end = i
                                    print(f"DEBUG: Found next tile header at offset {i}")
                                    break
                            except:
                                continue
                
                jpeg_data = data[:jpeg_end]
                data = data[jpeg_end:]
                
                print(f"DEBUG: JPEG data size: {len(jpeg_data)} bytes")
                
                # Decode tile
                try:
                    tile_pixmap = QPixmap()
                    if tile_pixmap.loadFromData(jpeg_data, 'JPEG'):
                        # Update tile cache
                        tile_key = (x, y)
                        self.tile_cache[tile_key] = (tile_pixmap, tile_width, tile_height)
                        
                        # Update image size estimate if needed
                        if self.image_size is None:
                            # Estimate based on tile position + size
                            max_x = max((x + w for (x, y), (p, w, h) in self.tile_cache.items()), default=1920)
                            max_y = max((y + h for (x, y), (p, w, h) in self.tile_cache.items()), default=1080)
                            self.image_size = (max_x, max_y)
                        
                        tiles_processed += 1
                        print(f"DEBUG: Successfully processed tile {tiles_processed}/{num_tiles} at ({x},{y})")
                    else:
                        print(f"DEBUG: Failed to load tile JPEG data at ({x},{y}) - invalid JPEG")
                        
                except Exception as e:
                    print(f"Tile decode error at ({x},{y}): {e}")
                    continue
                
                tile_index += 1
            
            print(f"DEBUG: Processed {tiles_processed} tiles total out of {num_tiles}")
            
            # Reconstruct full image from tiles
            self._reconstruct_image_from_tiles()
            
        except Exception as e:
            print(f"Tile processing error: {e}")
            import traceback
            traceback.print_exc()
    
    def _reconstruct_image_from_tiles(self):
        """Reconstruct full image from cached tiles for PyQt5"""
        if not self.tile_cache:
            print("No tiles in cache, skipping reconstruction")
            return
        
        if self.image_size is None:
            print("No image size set, skipping reconstruction")
            return
        
        try:
            print(f"Reconstructing image from {len(self.tile_cache)} tiles, size {self.image_size}")
            
            # Create full image
            full_image = QImage(self.image_size[0], self.image_size[1], QImage.Format_RGB888)
            full_image.fill(Qt.black)  # Fill with black background
            
            # Create painter to draw tiles
            painter = QPainter(full_image)
            
            # Draw tiles
            tiles_drawn = 0
            for (x, y), (tile_pixmap, tile_width, tile_height) in self.tile_cache.items():
                # Ensure tile fits within image bounds
                if x + tile_width <= self.image_size[0] and y + tile_height <= self.image_size[1]:
                    painter.drawPixmap(x, y, tile_pixmap)
                    tiles_drawn += 1
            
            painter.end()
            
            print(f"Drew {tiles_drawn} tiles, displaying image")
            
            # Convert to pixmap and display
            full_pixmap = QPixmap.fromImage(full_image)
            if not full_pixmap.isNull():
                self.set_pixmap_with_aspect_ratio(full_pixmap)
                print("Image displayed successfully")
            else:
                print("Failed to create pixmap from reconstructed image")
            
            # Clear tile cache after reconstruction to prevent memory buildup
            self.tile_cache.clear()
            
        except Exception as e:
            print(f"Image reconstruction error: {e}")
            import traceback
            traceback.print_exc()
    
    def process_jpeg_data(self, data: bytes):
        """Process image data (WebP/JPEG) or delta updates - ultra-optimized for minimum latency"""
        if data.startswith(b'DELTA'):
            # Delta update: apply patch to base image
            import struct
            header_size = 4 * 4  # 4 ints for bbox
            bbox_data = data[5:5+header_size]
            x1, y1, x2, y2 = struct.unpack('<IIII', bbox_data)
            region_data = data[5+header_size:]
            
            # Load region pixmap
            region_pixmap = QPixmap()
            if region_pixmap.loadFromData(region_data, 'JPEG'):
                # Create painter to apply patch
                if self.base_image is None:
                    # Fallback: treat as full image
                    self.original_pixmap = region_pixmap
                    self.image_label.setPixmap(region_pixmap)
                    return
                
                # Apply patch to base image
                painter = QPainter(self.base_image)
                painter.drawPixmap(x1, y1, region_pixmap)
                painter.end()
                
                # Update display
                self.original_pixmap = QPixmap.fromImage(self.base_image)
                self.image_label.setPixmap(self.original_pixmap)
        else:
            # Full image
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.original_pixmap = pixmap
                self.base_image = pixmap.toImage()  # Store as QImage for patching
                self.image_label.setPixmap(pixmap)
    
    def update_fps_label(self, fps_text):
        """Update FPS label (thread-safe)"""
        self.fps_display.setText(fps_text)
    
    def set_pixmap_with_aspect_ratio(self, pixmap):
        """Set pixmap maintaining aspect ratio - optimized for speed"""
        if pixmap.isNull():
            return
        
        # Store original pixmap
        self.original_pixmap = pixmap
        
        # Get the label size
        label_size = self.image_label.size()
        
        # Check if scaling is needed
        if pixmap.size() == label_size:
            self.image_label.setPixmap(pixmap)
            return
        
        # Use fast transformation for better FPS
        scaled_pixmap = pixmap.scaled(
            label_size, 
            Qt.KeepAspectRatio, 
            Qt.FastTransformation  # Faster rendering
        )
        
        self.image_label.setPixmap(scaled_pixmap)
    
    def window_resize_event(self, event):
        """Handle window resize events - instant response"""
        # Immediately re-scale without animation delays
        if self.original_pixmap:
            # Disable updates temporarily for instant resize
            self.image_label.setUpdatesEnabled(False)
            self.set_pixmap_with_aspect_ratio(self.original_pixmap)
            self.image_label.setUpdatesEnabled(True)
            self.image_label.repaint()  # Force immediate repaint
        
        # Call the original resize event
        QMainWindow.resizeEvent(self.window, event)
    
    def run(self):
        """Run the PyQt5 application"""
        if self.app:
            self.app.exec_()
    

    
    def write_message(self, data):
        """Delegate to protocol"""
        if self.protocol:
            self.protocol.write_message(data)
    
    def _send_worker(self):
        """Delegate to protocol"""
        if self.protocol:
            return self.protocol._send_worker()
    
    def _receive_worker(self):
        """Delegate to protocol"""
        if self.protocol:
            return self.protocol._receive_worker()
    
    @property
    def socket(self):
        """Get socket from protocol"""
        return self.protocol.socket if self.protocol else None
    
    @socket.setter
    def socket(self, value):
        """Set socket on protocol"""
        if self.protocol:
            self.protocol.socket = value
    
    @property
    def running(self):
        """Get running state from protocol"""
        return self.protocol.running if self.protocol else False
    
    @running.setter
    def running(self, value):
        """Set running state on protocol"""
        if self.protocol:
            self.protocol.running = value
    
    def stop(self):
        """Stop the application"""
        if self.protocol:
            self.protocol.stop()
        if self.window:
            self.window.close()
        if self.app:
            self.app.quit()

def create_pyqt5_controller_protocol():
    """Factory function to create PyQt5 controller protocol"""
    return PyQt5ControllerProtocol()

if __name__ == "__main__":
    """Run the PyQt5 controller application"""
    import sys
    
    # Create and run the controller
    controller = PyQt5ControllerProtocol()
    controller.run()