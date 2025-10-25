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

class PyQt5ControllerProtocol(QObject):
    """Ultra-modern PyQt5-based controller with superior performance"""
    
    # Signals for thread-safe GUI updates
    image_received = pyqtSignal(bytes)
    fps_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.app = None
        self.window = None
        self.last_received_time = time.time()
        self.transport = None
        
        # Transport compatibility attributes
        self._send_worker = None
        self._receive_worker = None
        self.socket = None
        self.running = True
        self.send_queue = queue.Queue()
        
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
            
        self.window = QMainWindow()
        self.window.setWindowTitle("Python Remote Desktop - PyQt5 Controller")
        self.window.setGeometry(100, 100, 1200, 800)
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
        self.image_label.setScaledContents(True)
        self.image_label.setMinimumSize(800, 600)
        layout.addWidget(self.image_label)
        
        # Setup mouse and keyboard events
        self.image_label.mousePressEvent = self.mouse_press_event
        self.image_label.mouseReleaseEvent = self.mouse_release_event
        self.image_label.wheelEvent = self.wheel_event
        self.window.keyPressEvent = self.key_press_event
        self.window.keyReleaseEvent = self.key_release_event
        
        # Focus policy for key events
        self.window.setFocusPolicy(Qt.StrongFocus)
        
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
        self.fps_slider.setRange(15, 144)
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
        """Convert screen coordinates to relative position"""
        rect = self.image_label.geometry()
        return (x / rect.width(), y / rect.height())
    
    def mouse_press_event(self, event):
        """Handle mouse press events"""
        pos = self.get_relative_position(event.x(), event.y())
        self.send_command('MoveMouse', pos[0], pos[1])
        self.send_command('MouseInput', event.button() == Qt.LeftButton, True)
    
    def mouse_release_event(self, event):
        """Handle mouse release events"""
        pos = self.get_relative_position(event.x(), event.y())
        self.send_command('MoveMouse', pos[0], pos[1])
        self.send_command('MouseInput', event.button() == Qt.LeftButton, False)
    
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
        
    def set_send_worker(self, send_worker):
        """Set send worker for compatibility with raw transport"""
        self._send_worker = send_worker
        
    def set_receive_worker(self, receive_worker):
        """Set receive worker for compatibility with raw transport"""  
        self._receive_worker = receive_worker
    
    def connection_made(self):
        """Called when connection is established"""
        print("PyQt5 Controller connected!")
        self.window.show()
        
        # Request first screenshot
        self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
    
    def message_received(self, data: bytes):
        """Handle received messages (called from transport thread)"""
        try:
            current_time = time.time()
            
            # Calculate and emit FPS
            if hasattr(self, 'last_received_time'):
                fps = 1.0 / (current_time - self.last_received_time)
                self.fps_updated.emit(f"{fps:.1f}")
            
            self.last_received_time = current_time
            
            # Emit signal for image processing (thread-safe)
            self.image_received.emit(data)
            
            # Request next screenshot
            self.write_message(COMMAND_SEND_SCREENSHOT.encode('ascii'))
            
        except Exception as e:
            print(f"PyQt5 Controller message error: {e}")
    
    def update_display(self, data: bytes):
        """Update display with received image data (runs in main thread)"""
        try:
            # Process image data
            if data.startswith(b'NUMPY'):
                self.process_numpy_data(data[5:])
            else:
                self.process_jpeg_data(data)
        except Exception as e:
            print(f"Display update error: {e}")
    
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
            
            # Convert to QImage
            img_array = np.frombuffer(array_bytes, dtype=np.uint8).reshape((height, width, channels))
            
            # Create QImage (RGB format)
            qimage = QImage(img_array.data, width, height, width * 3, QImage.Format_RGB888)
            
            # Convert to QPixmap and display
            pixmap = QPixmap.fromImage(qimage)
            self.image_label.setPixmap(pixmap)
            
        except Exception as e:
            print(f"Numpy processing error: {e}")
    
    def process_jpeg_data(self, data: bytes):
        """Process JPEG image data"""
        try:
            # Load with PIL first, then convert to Qt
            pil_image = Image.open(io.BytesIO(data))
            
            # Convert PIL to numpy array
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            img_array = np.array(pil_image)
            height, width, channels = img_array.shape
            
            # Create QImage
            qimage = QImage(img_array.data, width, height, width * 3, QImage.Format_RGB888)
            
            # Convert to QPixmap and display
            pixmap = QPixmap.fromImage(qimage)
            self.image_label.setPixmap(pixmap)
            
        except Exception as e:
            print(f"JPEG processing error: {e}")
    
    def update_fps_label(self, fps_text):
        """Update FPS label (thread-safe)"""
        self.fps_display.setText(fps_text)
    
    def run(self):
        """Run the PyQt5 application"""
        if self.app:
            self.app.exec_()
    
    def _send_worker(self):
        """Send worker thread for raw socket compatibility"""
        while getattr(self, 'running', True):
            try:
                if hasattr(self, 'send_queue') and not self.send_queue.empty():
                    data = self.send_queue.get()
                    if hasattr(self, 'socket') and data:
                        self.socket.sendall(data)
                else:
                    time.sleep(0.001)  # Small delay to prevent busy waiting
            except Exception as e:
                print(f"Send worker error: {e}")
                break
    
    def _receive_worker(self):
        """Receive worker thread for raw socket compatibility"""
        while getattr(self, 'running', True):
            try:
                if hasattr(self, 'socket'):
                    data = self.socket.recv(8192)
                    if data:
                        self.message_received(data)
                    else:
                        break
            except Exception as e:
                print(f"Receive worker error: {e}")
                break
    
    def write_message(self, data):
        """Write message via socket (compatibility method)"""
        try:
            if hasattr(self, 'socket'):
                self.socket.sendall(data)
        except Exception as e:
            print(f"Write message error: {e}")
    
    def stop(self):
        """Stop the application"""
        self.running = False
        if self.window:
            self.window.close()
        if self.app:
            self.app.quit()

def create_pyqt5_controller_protocol():
    """Factory function to create PyQt5 controller protocol"""
    return PyQt5ControllerProtocol()