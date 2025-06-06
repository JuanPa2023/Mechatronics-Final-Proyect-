# ------------- PROYECTO FINAL G & S--------------------
## LIBRERIAS
import cv2
import numpy as np
import mediapipe as mp
import pickle
import os
import time
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Dense, Dropout, BatchNormalization
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.regularizers import l2
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

# Comunicación y cámara
import socket
import queue

# Voz
import pyttsx3
import threading
from collections import deque

# Módulos para reconocimiento de voz
import speech_recognition as sr
import librosa
import io
import wave
## UDP
# Configuración para el reconocimiento de voz
SAMPLE_RATE_IN = 48000  # Tasa del micrófono INMP441
SAMPLE_RATE_OUT = 16000  # Tasa requerida por la API de reconocimiento
BUFFER_DURATION = 5  # segundos


UDP_IP_PI = "192.168.7.2"  # IP de la Raspberry Pi
UDP_OPEN = '0.0.0.0'

# Puertos para diferentes servicios
UDP_PORT_MICROFONO = 5006
UDP_PORT_TEXT = 5005
UDP_PORT_SERVO = 5001  # Puerto para enviar comandos
UDP_PORT_PARLANTE = 5003
UDP_PORT_CAM = 5002  # Puerto para recibir video
MAX_PACKET_SIZE = 1400  # Tamaño máximo del paquete UDP


## VOZ A PANTALLA
### RECONOCEDOR DE VOZ
# Inicializar el reconocedor de voz
recognizer = sr.Recognizer()

# Configuración UDP para voz
sock_voice = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
microfono_queue = queue.Queue()

# Variable para controlar el servicio de reconocimiento de voz
speech_recognition_running = True #VA EN EL WHILE.

# Variable para almacenar la última transcripción
last_transcription = "" #NO ESTAN EN SPEECH-TO-TEXT-FREE-UDP-V1.PY

def recibir_audio():
    sock_audio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock_audio.bind(("0.0.0.0", UDP_PORT_MICROFONO))
        
        buffer = bytearray()
        bytes_needed = SAMPLE_RATE_IN * 4 * BUFFER_DURATION  # 4 bytes por muestra (32-bit)
        
        while speech_recognition_running:
            data, _ = sock_audio.recvfrom(4096)
            buffer.extend(data)
            
            while len(buffer) >= bytes_needed:
                # Extraer 5 segundos de audio
                chunk = bytes(buffer[:bytes_needed])
                del buffer[:bytes_needed]
                
                # Convertir a formato numpy
                audio_int32 = np.frombuffer(chunk, dtype=np.int32)
                audio_float32 = audio_int32.astype(np.float32) / 2**31
                
                # Remuestrear a 16kHz
                audio_16k = librosa.resample(
                    audio_float32,
                    orig_sr=SAMPLE_RATE_IN,
                    target_sr=SAMPLE_RATE_OUT
                )
                
                # Convertir a int16 para la API de reconocimiento
                audio_int16 = (audio_16k * 32767).astype(np.int16)
                
                # Crear un archivo WAV en memoria
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 2 bytes por muestra (16 bits)
                    wav_file.setframerate(SAMPLE_RATE_OUT)
                    wav_file.writeframes(audio_int16.tobytes())
                
                wav_buffer.seek(0)  # Rebobinar el buffer
                microfono_queue.put(wav_buffer)
    except Exception as e:
        print(f"Error en recibir_audio: {e}")
    #NO ESTAN EN SPEECH-TO-TEXT-FREE-UDP-V1.PY  ver de comentarlo
    finally: 
        sock_audio.close() 
### PROCESAR AUDIO
def procesar_audio():
    global last_transcription #NO ESTAN EN SPEECH-TO-TEXT-FREE-UDP-V1.PY
    while speech_recognition_running:
        try:
            wav_buffer = microfono_queue.get(timeout=1)
            
            # Crear un objeto AudioData desde el buffer WAV
            with sr.AudioFile(wav_buffer) as source:
                audio_data = recognizer.record(source)
            
            # Realizar la transcripción usando la API gratuita de Google
            transcription = recognizer.recognize_google(audio_data, language="es-ES")
            
            print(f"Transcripción: {transcription}")
            last_transcription = transcription #NO ESTAN EN SPEECH-TO-TEXT-FREE-UDP-V1.PY
            
            # Enviar transcripción por UDP si es necesario
            sock_voice.sendto(transcription.encode(), (UDP_IP_PI, UDP_PORT_TEXT))
            
        except queue.Empty:
            continue
        except sr.UnknownValueError:
            print("No se detectó voz en el audio")
        except sr.RequestError as e:
            print(f"Error en la solicitud a la API de Google: {e}")
        except Exception as e:
            print(f"Error en la transcripción: {e}")
### ACTIVACION DE RECONOCIMIENTO DE VOZ
# Función para iniciar el servicio de reconocimiento de voz
def start_speech_recognition():
    global speech_recognition_running
    speech_recognition_running = True
    
    # Iniciar hilos para el reconocimiento de voz
    audio_thread = threading.Thread(target=recibir_audio, daemon=True)
    process_thread = threading.Thread(target=procesar_audio, daemon=True)
    
    audio_thread.start()
    process_thread.start()
    
    print("Servicio de reconocimiento de voz iniciado...")
    return audio_thread, process_thread
### DETENCION DE RECONOCIMIENTO DE VOZ
# Función para detener el servicio de reconocimiento de voz
def stop_speech_recognition():
    global speech_recognition_running
    speech_recognition_running = False
    sock_voice.close()
    print("Servicio de reconocimiento de voz detenido.")
## CAMARA
### MOTOR TEXTO-VOZ
# Configuración de directorios y archivos
audio_dir = "pyttsx3_audios"

# Socket UDP compartido
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Variable global para última reproducción
last_spoken_gesture = None

# Cola thread-safe
audio_queue = deque()
queue_lock = threading.Lock()
processing_event = threading.Event()

def sanitize_filename(text):
    return text.replace(' ', '_').lower() + '.wav'

def get_audio_duration(file_path):
    """Obtiene duración precisa del archivo WAV"""
    try:
        with wave.open(file_path, 'r') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            return frames / float(rate)
    except:
        return 0.1  # Duración por defecto si hay error

def send_audio(file_path):
    """Envía archivo de audio por UDP sin delays intermedios"""
    try:
        with open(file_path, 'rb') as f:
            audio_data = f.read()
        
        # Envío rápido en chunks
        total_chunks = (len(audio_data) + MAX_PACKET_SIZE - 1) // MAX_PACKET_SIZE
        for i in range(total_chunks):
            chunk = audio_data[i*MAX_PACKET_SIZE:(i+1)*MAX_PACKET_SIZE]
            udp_socket.sendto(chunk, (UDP_IP_PI, UDP_PORT_PARLANTE))
        
        return get_audio_duration(file_path)
    
    except Exception as e:
        print(f"Error enviando audio: {str(e)}")
        return 0

def queue_processor():
    """Procesa la cola de forma eficiente"""
    while True:
        processing_event.wait()  # Espera hasta que haya elementos
        
        with queue_lock:
            if not audio_queue:
                processing_event.clear()
                continue
            
            text = audio_queue.popleft()
            filename = sanitize_filename(text)
            file_path = os.path.join(audio_dir, filename)
        
        if os.path.exists(file_path):
            duration = send_audio(file_path)
            print(f"Audio enviado: {filename} (Duración: {duration:.2f}s)")
            time.sleep(duration)  # Espera exacta según duración real
        else:
            print(f"Archivo no encontrado: {filename}")

# Iniciar hilo procesador una sola vez
processor_thread = threading.Thread(target=queue_processor, daemon=True)
processor_thread.start()

def speak_text(text):
    """Añade texto a la cola de reproducción"""
    filename = sanitize_filename(text)
    
    with queue_lock:
        # Evitar duplicados consecutivos
        if not audio_queue or audio_queue[-1] != text:
            audio_queue.append(text)
            processing_event.set()  # Reactivar procesamiento si estaba inactivo
### MEDIAPIPE
# Inicializar MediaPipe
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.5, #probar con 0.4
    min_tracking_confidence=0.5 #probar con 0.4
)
# Inicializar MediaPipe Pose
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
mp_drawing = mp.solutions.drawing_utils
### COMUNICACION CAMARA
class UDPCamera:
    def __init__(self):
        self.host = UDP_OPEN
        self.port = UDP_PORT_CAM
        self.buffer_size = 65536
        self.mtu = 1400
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2)
        self.frame = None
        self.fragments = []
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.start()

    def start(self):
        if not self.running:
            self.running = True
            self.sock.bind((self.host, self.port))
            self.thread = threading.Thread(target=self._receive_frames, daemon=True)
            self.thread.start()

    def _receive_frames(self):
        while self.running:
            try:
                fragment, _ = self.sock.recvfrom(self.buffer_size)
                with self.lock:
                    self.fragments.append(fragment)
                    if len(fragment) < self.mtu:  # Último fragmento
                        frame_bytes = b''.join(self.fragments)
                        self.fragments = []
                        frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                        self.frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error en recepción: {str(e)}")
                break

    def read(self):
        with self.lock:
            if self.frame is not None:
                return True, self.frame.copy()
            return False, None

    def release(self):
        self.running = False
        with self.lock:
            self.fragments = []
            self.frame = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.sock.close()

    def __del__(self):
        self.release()
### MODELO TFLITE
class TFLiteModel:
    def __init__(self, model_path):
        # Cargar el modelo TFLite
        self.interpreter = tf.lite.Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        
        # Obtener detalles de entrada y salida
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
    
    def predict(self, input_data):
        # Asegurar el tipo de dato correcto y agregar dimensión batch si es necesario
        input_data = np.array(input_data, dtype=self.input_details[0]['dtype'])
        if len(input_data.shape) == len(self.input_details[0]['shape']) - 1:
            input_data = np.expand_dims(input_data, axis=0)
        
        # Establecer la entrada y ejecutar la inferencia
        self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
        self.interpreter.invoke()
        
        # Obtener la salida
        output_data = self.interpreter.get_tensor(self.output_details[0]['index'])
        return output_data

# Configuración de TensorFlow para rendimiento
physical_devices = tf.config.list_physical_devices('GPU')
if physical_devices:
    # Configuración de TensorFlow para rendimiento en CPU
    try:
        # Verificar si hay GPU disponible (para futuras expansiones)
        physical_devices = tf.config.list_physical_devices('GPU')
        
        if physical_devices:
            # Configuración para GPU (no se ejecutará en tu caso)
            for device in physical_devices:
                tf.config.experimental.set_memory_growth(device, True)
            print("GPU disponible para aceleración")
        else:
            # Optimización para CPU
            tf.config.threading.set_intra_op_parallelism_threads(4)  # Aprovecha núcleos físicos
            tf.config.threading.set_inter_op_parallelism_threads(2)  # Paralelismo entre operaciones
            print("Modo CPU activado: Configuración optimizada para Intel Core i7-7500U")
            
    except Exception as e:
        print(f"Error de configuración: {str(e)}")
        print("Usando configuración por defecto de CPU")
### ARCHIVOS
# Configuración de directorios y archivos
data_dir = "hand_gestures_data_v15"
os.makedirs(data_dir, exist_ok=True)

# Modelo y datos de entrenamiento
model = None
# Inicializar scaler y label encoder
scaler = StandardScaler()
label_encoder = LabelEncoder()
model_file = "hand_gesture_nn_model_v15_POSE.h5"
scaler_file = "hand_gesture_scaler_v15_POSE.pkl"
encoder_file = "hand_gesture_encoder_v15_POSE.pkl"
gesture_data = "gesture_data_v15_POSE.pkl" 
model_tflite = "modelo_optimizadotl_v15_POSE.tflite"

# Variables globales para estado
data = []
labels = []

# Estado del sistema
is_trained = False
is_collecting = False
current_gesture = ""
samples_collected = 0
max_samples = 5000

# Control de tiempo para la recolección continua
last_sample_time = 0
sample_delay = 0.05  # 50ms entre muestras

# Temporizador para mostrar mensajes
message = ""
message_until = 0

# Para evaluación del modelo
metrics = {
    'accuracy': 0,
    'val_accuracy': 0,
    'training_time': 0
}
### EXTRACCION DE LANDMARKS
send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # socket de los puntos de la muñeca

def extract_hand_pose_landmarks(frame, send_sock=None):
    """
    Extrae landmarks de las manos y del cuerpo, y realiza seguimiento de la muñeca derecha.
    
    Args:
        frame: Imagen en formato BGR
        send_sock: Socket UDP opcional para enviar datos de seguimiento
    
    Returns:
        tuple: (landmarks_data, hands_detected, pose_detected)
    """
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # Procesar manos
    hands_results = hands.process(frame_rgb)
    
    # Procesar pose
    pose_results = pose.process(frame_rgb)
    
    # Inicializar variables
    hand_landmarks_data = []
    pose_landmarks_data = []
    hands_detected = False
    pose_detected = False
    x_normalized = None
    right_wrist_pixel = None
    
    # Extraer landmarks de manos
    if hands_results.multi_hand_landmarks:
        hands_detected = True
        # Procesar ambas manos para landmarks
        for hand_idx, hand_landmarks in enumerate(hands_results.multi_hand_landmarks):
            # Dibujar landmarks
            mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
            
            # Extraer coordenadas
            landmarks = []
            for landmark in hand_landmarks.landmark:
                landmarks.extend([landmark.x, landmark.y, landmark.z])
            hand_landmarks_data.extend(landmarks)
            
            # Detectar mano derecha para seguimiento
            if hands_results.multi_handedness:
                handedness = hands_results.multi_handedness[hand_idx]
                if handedness.classification[0].label == 'Left' and not x_normalized:
                    wrist = hand_landmarks.landmark[mp_hands.HandLandmark.WRIST]
                    
                    # Calcular coordenadas normalizadas
                    x_normalized = int((wrist.x - 0.5) * 15)  # Rango -7.5 a 7.5
                    print(x_normalized)
                    
                    # Obtener coordenadas para dibujo
                    right_wrist_pixel = mp_drawing._normalized_to_pixel_coordinates(
                        wrist.x, wrist.y, frame.shape[1], frame.shape[0]
                    )

        # Enviar datos y dibujar si se detectó mano derecha
        if x_normalized is not None:
            if send_sock:  # Solo enviar si se provee socket
                send_sock.sendto(
                    str(x_normalized).encode(),
                    (UDP_IP_PI, UDP_PORT_SERVO)  # Asegurar que estas constantes están definidas
                )
            if right_wrist_pixel:
                cv2.circle(frame, right_wrist_pixel, 10, (0, 255, 0), -1)
    
    # Rellenar con ceros si no hay manos
    while len(hand_landmarks_data) < 21 * 3 * 2:  # 21 landmarks * 3 coordenadas * 2 manos
        hand_landmarks_data.append(0.0)
    hand_landmarks_data = hand_landmarks_data[:21 * 3 * 2]  # Limitar a exactamente 126 valores
    
    # Extraer landmarks de pose
    if pose_results.pose_landmarks:
        pose_detected = True
        # Dibujar landmarks de pose
        mp_drawing.draw_landmarks(
            frame, 
            pose_results.pose_landmarks, 
            mp_pose.POSE_CONNECTIONS,
            mp_drawing.DrawingSpec(color=(245, 117, 66), thickness=2, circle_radius=2),
            mp_drawing.DrawingSpec(color=(245, 66, 230), thickness=2, circle_radius=1)
        )
        
        # Extraer coordenadas de los 33 landmarks de pose
        for landmark in pose_results.pose_landmarks.landmark:
            pose_landmarks_data.extend([landmark.x, landmark.y, landmark.z])
    
    # Rellenar con ceros si no hay pose detectada
    while len(pose_landmarks_data) < 33 * 3:  # 33 landmarks * 3 coordenadas
        pose_landmarks_data.append(0.0)
    pose_landmarks_data = pose_landmarks_data[:33 * 3]  # Limitar a exactamente 99 valores
    
    # Concatenar landmarks de manos y pose
    combined_landmarks = hand_landmarks_data + pose_landmarks_data
    
    return combined_landmarks, hands_detected, pose_detected
def set_message(message_text, duration=2):
    global message, message_until
    message = message_text
    message_until = time.time() + duration
### CARGA DE DATOS
def load_data():
    global data, labels
    try:
        with open(f"{data_dir}/{gesture_data}", "rb") as f:
            loaded_data = pickle.load(f)
            data = loaded_data["features"]
            labels = loaded_data["labels"]
        set_message(f"Datos cargados: {len(data)} muestras", 2)
        return True
    except Exception as e:
        print(f"Error al cargar datos: {e}")
        set_message("No se encontraron datos previos", 2)
        return False
### RED NEURONAL
def check_model_exists():
    return os.path.exists(model_file) and os.path.exists(scaler_file) and os.path.exists(encoder_file)

def create_neural_network(input_shape, num_classes):
    model = Sequential([
        Dense(64, activation='relu', input_shape=(input_shape,), kernel_regularizer=l2(0.001)),
        BatchNormalization(),
        Dropout(0.3),
        Dense(32, activation='relu', kernel_regularizer=l2(0.001)),
        BatchNormalization(),
        Dropout(0.2),
        Dense(num_classes, activation='softmax')
    ])
    
    model.compile(
        optimizer=Adam(learning_rate=0.001),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    
    return model
### CARGA DEL MODELO ENTRENADO
def load_saved_model():
    global scaler, label_encoder
    try:
        model = load_model(model_file)
        with open(scaler_file, 'rb') as f:
            scaler = pickle.load(f)
        with open(encoder_file, 'rb') as f:
            label_encoder = pickle.load(f)
        set_message("Modelo cargado correctamente", 2)
        return model
    except Exception as e:
        print(f"Error al cargar el modelo: {e}")
        set_message("Error al cargar el modelo", 2)
        return None

### MODELO DE TFLITE
def predict_tflite(landmarks, tflite_model, scaler, label_encoder, threshold=0.5):
    try:
        # Preprocesar los landmarks
        landmarks_array = np.array(landmarks).reshape(1, -1)
        landmarks_scaled = scaler.transform(landmarks_array)
        
        # Realizar predicción
        predictions = tflite_model.predict(landmarks_scaled)[0]
        
        # Obtener la clase con mayor probabilidad
        max_prob_idx = np.argmax(predictions)
        confidence = predictions[max_prob_idx]
        
        if confidence >= threshold:
            # Decodificar la etiqueta
            predicted_label = label_encoder.inverse_transform([max_prob_idx])[0]
            return predicted_label, confidence
        else:
            return "Desconocido", confidence
    except Exception as e:
        print(f"Error en la predicción: {e}")
        return "Error", 0.0

### CONVERSION A TFLITE
def convert_to_tflite(model_file, model_tflite):
    try:
        if not os.path.exists(model_file):
            raise FileNotFoundError(f"El archivo {model_file} no existe.")
        
        # Cargar el modelo entrenado
        modelo = load_model(model_file)
        
        # Convertir a TensorFlow Lite
        converter = tf.lite.TFLiteConverter.from_keras_model(modelo)
        tflite_model = converter.convert()
        
        # Guardar el modelo convertido
        with open(model_tflite, "wb") as f:
            f.write(tflite_model)
        
        print("Modelo convertido a TensorFlow Lite.")
    except Exception as e:
        print("Error al convertir el modelo a TFLite:", e)
### MENU
def print_menu():
    print("\n=== MENU PRINCIPAL ===")
    print("1. Listar señas cargadas")
    print("2. Evaluar en tiempo real")
    print("0. Salir")

### LISTADO DE GESTOS
def list_gestures():
    # Asumiendo que 'labels' es la lista donde se guardan las señas
    if not labels:
        print("No hay señas guardadas.")
    else:
        unique_gestures = list(set(labels))
        print("\n--- Señas Guardadas ---")
        for i, gesture in enumerate(unique_gestures, 1):
            print(f"{i}. {gesture}")

### EVALUACION EN TIEMPO REAL
def run_evaluation_mode():
    global model_tflite, last_spoken_gesture
    # Inicializa el modelo TFLite si aún no se ha cargado
    if os.path.exists(model_tflite):
        tflite_model = TFLiteModel(model_tflite)
    else:
        print("El modelo TFLite no existe. Conviértelo primero.")
        return

    # Inicia la cámara
    try:
        cap = UDPCamera()
        print("Cámara UDP iniciada para evaluación en tiempo real.")
    except Exception as e:
        print(f"Error al iniciar la cámara: {str(e)}")
        return
    
    #NUEVO BARRITA DE PROGRESO
    # Variables para el sistema de confirmación de señas
    consecutive_frames = 0
    last_prediction = ""
    confirmation_threshold = 5  # Número de frames consecutivos necesarios
    confirmed_gesture = ""
    
    # Para el enfoque alternativo de ventana deslizante
    window_size = 5
    prediction_window = []
    
    # Umbral de confianza para considerar una detección válida
    confidence_threshold = 0.9

    
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        landmarks, hands_detected, pose_detected = extract_hand_pose_landmarks(frame, send_sock)
        frame_h, frame_w, _ = frame.shape

        # Mostrar información de detección
        detection_info = []
        if hands_detected:
            detection_info.append("Manos")
        if pose_detected:
            detection_info.append("Pose")
            
        detection_text = ", ".join(detection_info) if detection_info else "Nada detectado"
        cv2.putText(frame, f"Detectado: {detection_text}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        #NUEVO BARRITA DE PROGRESO
        # Mostrar información de detección
        detection_info = []
        if hands_detected:
            detection_info.append("Manos")
        if pose_detected:
            detection_info.append("Pose")
            
        detection_text = ", ".join(detection_info) if detection_info else "Nada detectado"
        cv2.putText(frame, f"Detectado: {detection_text}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        if hands_detected or pose_detected:
            prediction, confidence = predict_tflite(landmarks, tflite_model, scaler, label_encoder, threshold=confidence_threshold)
            
            # Extraer predicción y mostrar en pantalla
            prediction_window.append(prediction)
            if len(prediction_window) > window_size:
                prediction_window.pop(0)
            
            # Contar ocurrencias de cada predicción en la ventana
            prediction_counts = {}
            for pred in prediction_window:
                if pred in prediction_counts:
                    prediction_counts[pred] += 1
                else:
                    prediction_counts[pred] = 1
            
            # Encontrar la predicción más frecuente
            most_common = max(prediction_counts.items(), key=lambda x: x[1]) if prediction_counts else ("Desconocido", 0)
            stable_prediction, count = most_common
            
            # Solo considerar predicciones estables (más de la mitad de la ventana)
            if count >= window_size // 2 and stable_prediction != "Desconocido" and stable_prediction != "Error":
                # Mostrar predicción estable
                cv2.putText(frame, f"{stable_prediction} ({confidence:.2f})", (10, 70), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                
                # Reproducir audio si es una nueva predicción estable
                if stable_prediction != last_spoken_gesture:
                    speak_text(stable_prediction)
                    last_spoken_gesture = stable_prediction
            else:
                # Mostrar predicción actual con confianza
                cv2.putText(frame, f"{prediction} ({confidence:.2f})", (10, 70), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        else:
            # Reiniciar ventana si no hay detección
            prediction_window = []
            cv2.putText(frame, "No hay detección", (10, 70), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Mostrar transcripción de voz en pantalla
        if last_transcription:
            cv2.putText(frame, f"Voz: {last_transcription}", (10, frame_h - 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Mostrar frame
        cv2.imshow("Evaluación de Señas", frame)
        
        # Salir con la tecla 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    # Liberar recursos
    cap.release()
    cv2.destroyAllWindows()
    stop_speech_recognition()
### FUNCION PRINCIPAL 
def main():
    global model, is_trained, data, labels

    # Iniciar el servicio de reconocimiento de voz al iniciar el programa
    print("Iniciando servicio de reconocimiento de voz...")
    speech_threads = start_speech_recognition()
    print("Servicio de reconocimiento de voz iniciado correctamente.")
    
    # Inicialización del sistema
    is_trained = False
    model = None
    data = []
    labels = []
    
    # Cargar datos existentes
    load_data()
    
    # Intentar cargar modelo si existe
    if check_model_exists():
        model = load_saved_model()
        is_trained = True
    else:
        is_trained = False

    # Mostrar el menú en la consola
    print_menu()

    # Bucle principal de selección en consola
    while True:
        opcion = input("\nSelecciona una opción (Señas: 1, Evaluar: 2, Salir: 0): ").strip()
                
        if opcion == '1':
            list_gestures()  # Lista las señas cargadas

        elif opcion == '2':
            if is_trained:
                # Inicializar modo evaluación en tiempo real
                print("Modo de evaluación activado.")
                run_evaluation_mode()
            else:
                print("¡Entrena el modelo primero (Opción 2)!")
                
        elif opcion == '0':
            print("Deteniendo servicio de reconocimiento de voz...")
            stop_speech_recognition()
            print("Saliendo del programa...")
            break
        else:
            print("Opción inválida, intenta nuevamente.")
        
        # Mostrar nuevamente el menú luego de finalizar la opción seleccionada.
        print_menu()

if __name__ == "__main__":
    main()