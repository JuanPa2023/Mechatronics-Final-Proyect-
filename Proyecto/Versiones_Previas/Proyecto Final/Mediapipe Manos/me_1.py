import cv2
import mediapipe as mp

# Inicializa MediaPipe para manos
mp_hands = mp.solutions.hands #MediaPipe tiene una solución preconfigurada para detectar manos y rastrear los puntos clave de las mismas.
hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5)# Este objeto se usa para inicializar el detector de manos en tiempo real, donde podemos configurar parámetros como la cantidad máxima de manos a detectar y el nivel de confianza para la detección.
mp_draw = mp.solutions.drawing_utils

# Captura desde la cámara
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Convertir a RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb_frame)#Procesa la imagen en formato RGB y devuelve las coordenadas de los puntos clave de las manos si las detecta

    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

    cv2.imshow("Detección de Manos", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # Salir con 'ESC'
        break

cap.release()
cv2.destroyAllWindows()

import os
import numpy as np

# Directorio para guardar datos
dataset_dir = "dataset" #Creamos un directorio donde se almacenarán las señales, con una subcarpeta para cada gesto (letra o palabra).
os.makedirs(dataset_dir, exist_ok=True)

gesture = "2"  # Cambia según el gesto
save_dir = os.path.join(dataset_dir, gesture)
os.makedirs(save_dir, exist_ok=True)

cap = cv2.VideoCapture(0)
counter = 0

"""Captura de frames: El ciclo while captura los frames de la cámara 
y convierte la imagen de BGR a RGB para ser procesada por MediaPipe."""

while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb_frame)

#Extracción de landmarks: Para cada mano detectada, extraemos 
#las coordenadas x, y, z de los puntos clave de los landmarks 
#(por ejemplo, la punta de los dedos, la base de la palma, etc.).

    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            # Extrae puntos clave
            landmarks = []
            for lm in hand_landmarks.landmark:
                landmarks.append([lm.x, lm.y, lm.z])


#Guardado de datos: Los puntos clave de cada frame se aplanan (flatten) 
#a un vector y luego se guardan en un archivo .npy en el directorio 
#correspondiente al gesto (letra)

            # Guarda como archivo .npy
            landmarks = np.array(landmarks).flatten()
            np.save(os.path.join(save_dir, f"frame_{counter}.npy"), landmarks)
            counter += 1

    cv2.imshow("Recolección de Datos", frame)
    if cv2.waitKey(1) & 0xFF == 27 or counter >= 100:  # Salir con 'ESC'
        break

cap.release()
cv2.destroyAllWindows()


import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout

# Carga los datos
def load_data(dataset_dir):
    data = []
    labels = []
    for label, gesture in enumerate(os.listdir(dataset_dir)):
        gesture_dir = os.path.join(dataset_dir, gesture)
        for file in os.listdir(gesture_dir):
            filepath = os.path.join(gesture_dir, file)
            landmarks = np.load(filepath)
            data.append(landmarks)
            labels.append(label)
    return np.array(data), np.array(labels)

X, y = load_data("dataset")
y = tf.keras.utils.to_categorical(y, num_classes=len(os.listdir("dataset")))

# Define el modelo
model = Sequential([
    Dense(128, activation='relu', input_shape=(X.shape[1],)),
    Dropout(0.2),
    Dense(64, activation='relu'),
    Dropout(0.2),
    Dense(len(os.listdir("dataset")), activation='softmax')
])

model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

# Entrena el modelo
model.fit(X, y, epochs=20, batch_size=32, validation_split=0.2)
model.save("gesture_model.h5")


model = tf.keras.models.load_model("gesture_model.h5")

cap = cv2.VideoCapture(0)
while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb_frame)

    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            landmarks = []
            for lm in hand_landmarks.landmark:
                landmarks.append([lm.x, lm.y, lm.z])
            landmarks = np.array(landmarks).flatten()
            landmarks = np.expand_dims(landmarks, axis=0)

            prediction = model.predict(landmarks)
            gesture = np.argmax(prediction)
            print(f"Gesto detectado: {gesture}")

    cv2.imshow("Traducción de Señales", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # Salir con 'ESC'
        break

cap.release()
cv2.destroyAllWindows()
