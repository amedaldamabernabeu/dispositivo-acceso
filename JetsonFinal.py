import serial
import datetime
import os
import cv2
import sys
import pickle
import requests
import shutil
import numpy as np
import time

try:
    import pygame

    PYGAME_DISPONIBLE = True
except ImportError:
    pygame = None  # type: ignore[assignment]
    PYGAME_DISPONIBLE = False

from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt, QDate, QTimer
from PyQt5.QtGui import QImage, QPixmap, QIcon, QFont
from PyQt5.QtCore import pyqtSlot, QTimer
from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QApplication, QDialog

from sgaccuv_api import (
    cargar_config_sgaccuv,
    env_str,
    registrar_entrada_http,
    registrar_salida_http,
    validar_codigo_http,
)

# Opcional: en Windows suele faltar dlib/face_recognition; en Jetson/Linux suele estar instalado.
try:
    import face_recognition

    FACIAL_RECOGNITION_DISPONIBLE = True
except ImportError:
    face_recognition = None  # type: ignore[assignment]
    FACIAL_RECOGNITION_DISPONIBLE = False


def _reproducir_audio_mp3(ruta: str) -> None:
    """Reproduce un MP3 con pygame si el módulo está instalado; no-op si falta."""
    if not PYGAME_DISPONIBLE or pygame is None:
        return
    pygame.mixer.music.load(ruta)
    pygame.mixer.music.play()


# --- Integración SGACCUV: URL, token y tipos vía sgaccuv_api (variables SGACCUV_*). ---
MODE = (env_str("SGACCUV_MODE", "test") or "test").lower()


class Ui_OutputDialog(QDialog):
    def __init__(self):
        self.matchCounter = 5
        self.image = None
        self.Videocapture_ = None
        self.Videocapture_ = "0"
        super(Ui_OutputDialog, self).__init__()
        loadUi("./outputwindow.ui", self)
        self._sga = cargar_config_sgaccuv()
        self.main_route = "User"
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(107, 178, 235))  # Código RGB para lightblue
        self.setPalette(palette)
        self.resize(960,640)
        self.icono = QIcon('EscudoUDG.png')
        self.AccessGranted = QPixmap('AccessGranted.png')
        self.AccessDenied = QPixmap('AccessDenied.png')
        self.LogoCUValles= QPixmap("EscudoUDG.png")
        self.backGUser = QPixmap("FondoUsuario.png")
        self.UDG = QPixmap('EscudoUDG.png')
        self.setWindowIcon(self.icono)
        self.imgLabel_5.setPixmap(self.LogoCUValles)
        self.imgLabel_4.setPixmap(self.UDG)
        self.imgLabel_2.setScaledContents(True)
        self.imgLabel_3.setPixmap(self.backGUser)
        self.imgLabel_3.setScaledContents(True)
        self.imgLabel_5.setScaledContents(True)
        self.font = QFont()
        if PYGAME_DISPONIBLE:
            pygame.init()
        else:
            print(
                "[SGACCUV] pygame no importable: la app arranca sin reproducción de MP3."
            )
        self.initialUI()
        self.pushButton.clicked.connect(self.loginB)
        self.B1.clicked.connect(self.button1)
        self.B2.clicked.connect(self.button2)
        self.B3.clicked.connect(self.button3)
        self.B4.clicked.connect(self.button4)
        self.B5.clicked.connect(self.button5)
        self.B6.clicked.connect(self.button6)
        self.B7.clicked.connect(self.button7)
        self.B8.clicked.connect(self.button8)
        self.B9.clicked.connect(self.button9)
        self.limpiar.clicked.connect(self.buttonlimpiar)
        self.B0.clicked.connect(self.button0)
        self.borrar.clicked.connect(self.buttonborrar)
        self.show()
        self.startVideo(self.Videocapture_)
        self.now = QDate.currentDate()
        self.UserNotFound = b'{"return":"no permitido"}'
        self.UserAdmin = b'{"return":"acceso"}'
        self.regCreated = b'{"return":"Registro creado"}'
        self.regUpdate = b'{"return":"Registro Actualizado"}'
        self.regCompleted = b'{"return":"Registro completado"}'
        self.lectores = False
        self.camera = False
        self.registroId = None
        self._entrada_desde_rf = False
        self._salida_desde_rf = False
        if not FACIAL_RECOGNITION_DISPONIBLE:
            print(
                "[SGACCUV] face_recognition no importable: la app arranca; "
                "flujo por cámara tras correctID() queda desactivado hasta instalar el paquete."
            )
        #self.ESP32()
        

    def _consultar_validar(self, codigo):
        """GET /registro-acceso/validar/{codigo}. Devuelve dict o None si error HTTP/red."""
        return validar_codigo_http(self._sga, codigo)

    def _aplicar_respuesta_validar(self, data, desde_codid_rf=False):
        """Mapea la respuesta JSON del backend al flujo existente de la UI."""
        if not data or not data.get("valido"):
            return False
        if data.get("tipo") == "salida":
            rid = data.get("registroId")
            if rid is not None:
                self.registroId = int(rid)
            self._salida_desde_rf = desde_codid_rf
            self.lector = 2
            self.AccesoConcedido(False)
            return True
        if data.get("tipo") == "entrada":
            self.lector = 1
            self._entrada_desde_rf = desde_codid_rf
            self.AccesoConcedido(False)
            return True
        return False

    def _enviar_torniquete_entrada(self):
        if MODE == "test":
            print("SIMULACIÓN: Abriendo torniquete entrada")
            return
        if not getattr(self, "lectores", False) or not getattr(self, "ser", None):
            return
        value_to_send = "O1"
        self.ser.write(value_to_send.encode("utf-8"))
        self.lectura = str(self.ser.readline().decode("utf-8").strip())
        print(self.lectura)
        time.sleep(1)
        value_to_send = "C1"
        self.ser.write(value_to_send.encode("utf-8"))
        self.lectura = str(self.ser.readline().decode("utf-8").strip())
        print(self.lectura)

    def _enviar_torniquete_salida(self):
        if MODE == "test":
            print("SIMULACIÓN: Abriendo torniquete salida")
            return
        if not getattr(self, "lectores", False) or not getattr(self, "ser", None):
            return
        value_to_send = "O2"
        self.ser.write(str(value_to_send).encode("utf-8"))
        self.lectura = str(self.ser.readline().decode("utf-8").strip())
        print(self.lectura)
        time.sleep(1)
        value_to_send = "C2"
        self.ser.write(str(value_to_send).encode("utf-8"))
        self.lectura = str(self.ser.readline().decode("utf-8").strip())
        print(self.lectura)

    @pyqtSlot()
    def loginB(self):
        self.torniquete = True
        self.ID = self.lineEdit.text()
        self.SearchID = self.find_folder_ID(self.ID)
        self.labelMessage.setVisible(True)
        self.labelCodigo.setVisible(True)
        self.lector = 1
        if self.SearchID == 100:
            self.correctID()
        elif self.SearchID == 102:
            self._entrada_desde_rf = False
            self.AccesoConcedido(False)
        elif self.SearchID == 405:
            self.labelCodigo.setVisible(False)
            self.lineEdit.setVisible(False)
            self.lineEdit.setVisible(False)
            self.labelMessage.setVisible(True)
            self.labelMessage.setGeometry(self.x + 50, self.y + 400, 400, 61)
            self.labelMessage.setText("Error al conectar")
            QTimer.singleShot(1000, self.initialUI)
        elif self.SearchID == 101:
            self._salida_desde_rf = False
            self.lector = 2
            self.AccesoConcedido(False)
        else:
            self.incorrectID()
    def button0(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(0)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button1(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(1)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button2(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(2)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button3(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(3)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button4(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(4)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button5(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(5)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button6(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(6)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button7(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(7)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button8(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(8)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def button9(self):
        current_text = self.lineEdit.text()
        new_text = current_text + str(9)
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()
    def buttonlimpiar(self):
        self.lineEdit.setText("")
        self.lineEdit.setFocus()
    def buttonborrar(self):
        current_text = self.lineEdit.text()
        new_text = current_text[:-1]  # Eliminar el último carácter
        self.lineEdit.setText(new_text)
        self.lineEdit.setFocus()

    def keyPressEvent(self, qKeyEvent):
        self.ID = self.lineEdit.text()
        try:
            if qKeyEvent.key() == Qt.Key_Return or qKeyEvent.key() == Qt.Key_Enter:
                try:
                    self.torniquete = True
                    data = self._consultar_validar(self.ID)
                    print(data)
                    if data is None:
                        self.incorrectID()
                    elif not data.get("valido"):
                        self.incorrectID()
                    else:
                        self._aplicar_respuesta_validar(data, desde_codid_rf=False)
                except (requests.exceptions.RequestException, ValueError, TypeError) as e:
                    self.incorrectID()
                    print(f"Error al realizar la solicitud: {e}")
            elif qKeyEvent.key() == Qt.Key_Escape:
                print("Esc")
                audio_inicio = "Screen.mp3"
                _reproducir_audio_mp3(audio_inicio)
                
        except:
            pass

    def codID(self): #Lector RFID
        print("Torniquete", self.torniquete)
        self.torniquete = True
        id = int(self.ser.readline().decode('utf-8'))
        print(id)
        self.lector = int(self.ser.readline().decode('utf-8'))
        print(self.lector)

        #print(f"ID recibido: {id}")
        binario_completo = bin(id)[2:].zfill(29)
        #print(f"El valor en binario de 29 dígitos es: {binario_completo}")
        binario_recortado = binario_completo[7:] + '0'
        #print(f"El valor después de quitar 7 dígitos y agregar un 0 al final es: {binario_recortado}")
        valor_final_decimal = int(binario_recortado, 2)
        print(f"El valor final en decimal es: {valor_final_decimal}")
        self.lineEdit.setText(str(valor_final_decimal))
        self.ID = str(valor_final_decimal)
        if self.lector == 2:
            try:
                data = self._consultar_validar(str(valor_final_decimal))
                print(data)
                if data is None:
                    print("Ocurrió un error al realizar la solicitud.")
                elif not data.get("valido"):
                    self.lineEdit.setText("")
                    print("Código no válido")
                else:
                    self._aplicar_respuesta_validar(data, desde_codid_rf=True)
            except (requests.exceptions.RequestException, ValueError, TypeError):
                print("Except CODID")
        else:
            self.loginB()

    def find_folder_ID(self, codigo):
        id_usuario = codigo
        try:
            data = self._consultar_validar(str(id_usuario))
            print(data)
            if data is None:
                return 405
            if not data.get("valido"):
                return 404
            if data.get("tipo") == "salida":
                rid = data.get("registroId")
                if rid is not None:
                    self.registroId = int(rid)
                return 101
            if data.get("tipo") == "entrada":
                return 102
            return 404
        except (requests.exceptions.RequestException, ValueError, TypeError):
            return 405




    def Encode_Camera(self, imgS):
        print("Encode_Camera")
        if not FACIAL_RECOGNITION_DISPONIBLE or face_recognition is None:
            return -2
        count = 0
        # Coordenadas de recorte de displayImage
        y_start, y_end = 50, 530
        x_start, x_end = 50, 410
        # Recortar la imagen
        imgS = imgS[y_start:y_end, x_start:x_end]
        imgS = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)
        faceCurFrame = face_recognition.face_locations(imgS)
        if not faceCurFrame:
            return 0
        encodeCurFrame = face_recognition.face_encodings(imgS, faceCurFrame)
        green_box_drawn = False
        for encodeFace, faceLoc in zip(encodeCurFrame, faceCurFrame):
            matches = face_recognition.compare_faces(self.encodeListKnown, encodeFace)
            faceDis = face_recognition.face_distance(self.encodeListKnown, encodeFace)
            count += sum(matches)
            if self.muestras <= int(self.matchCounter*1.5) and self.bandera == False:
                self.muestras += 1
            top, right, bottom, left = faceLoc  # Coordenadas del cuadro
            if count >= 4 and not green_box_drawn:
                cv2.rectangle(imgS, (left, top), (right, bottom), (0, 255, 0), 2)  # Dibuja un recuadro verde
            # Convertir la imagen a formato QImage
                height, width, channel = imgS.shape
                bytesPerLine = 3 * width
                qImg = QImage(imgS.data, width, height, bytesPerLine, QImage.Format_RGB888)

            # Convertir a QPixmap y mostrar en el QLabel
                pixmap = QPixmap.fromImage(qImg)
                self.imgLabel.setPixmap(pixmap)
                self.imgLabel.setScaledContents(True)
            if count == 4 and self.coincidencias < self.matchCounter and self.coincidencias > self.matchCounter*-1 and self.muestras <= int(self.matchCounter*1.5):
                return 1
            elif count < 4 and self.muestras <= int(self.matchCounter*1.5):
                return -1
            else:
                return -2

    def startVideo(self, camera_name):
        #print("StartVideo")
        try:
            if len(camera_name) == 1:
                self.labelMessage.setVisible(False)
                self.lineEdit.setVisible(True)
                self.lineEdit.setFocus()
                self.labelCodigo.setVisible(True)
                self.capture = cv2.VideoCapture(int(camera_name))
                self.camera = True
                print("if")
            else:
                self.labelMessage.setVisible(False)
                self.lineEdit.setVisible(True)
                self.lineEdit.setFocus()
                self.labelCodigo.setVisible(True)
                self.capture = cv2.VideoCapture(camera_name)
                self.camera = True
                print("else")

            # Verificar si la cámara se abrió correctamente
            if not self.capture.isOpened():
                self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
                self.font.setPointSize(20)
                self.labelMessage.setFont(self.font)
                self.labelMessage.setAlignment(Qt.AlignCenter)
                self.labelMessage.setText('Camara no encontrada')
                self.labelMessage.setVisible(True)
                self.lineEdit.setVisible(False)
                self.labelCodigo.setVisible(False)
                self.camera = False
                self.startVideo(self.initialUI())
                raise ValueError("No se pudo abrir la cámara")



            self.timer = QTimer(self)  # Crear temporizador
            self.timer.timeout.connect(self.update_frame)  # Conectar el temporizador a la función de actualización
            self.timer.start(30)
        except Exception as e:
            self.camera = False
            print(f"Error al iniciar la cámara: {e}")


    def update_frame(self):
        #print("Upadate")
        self.concurrent_date = self.now.toString('ddd dd  MMMM yyyy')
        self.current_time = datetime.datetime.now().strftime("%I:%M %p")
        self.dateData.setText(self.concurrent_date)
        self.hourData.setText(self.current_time)
        if self.lectores == True:
            if self.ser.in_waiting > 0:
                self.codID()
            try:
                ret, self.image = self.capture.read()
                if not ret:
                    self.font.setPointSize(12)
                    self.labelMessage.setFont(self.font)
                    self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
                    self.labelMessage.setAlignment(Qt.AlignCenter)
                    self.labelMessage.setText('Camara no encontrada')
                    self.labelMessage.setVisible(True)
                    self.lineEdit.setVisible(False)
                    self.labelCodigo.setVisible(False)
                    QTimer.singleShot(5000, self.initialUI)
                    raise ValueError("No se pudo abrir la cámara.")
                self.image = cv2.resize(self.image, (0, 0), fx=0.5, fy=0.5)
                self.displayImage(self.image, 1)
                if self.SearchID == 100:
                    if not FACIAL_RECOGNITION_DISPONIBLE:
                        if not getattr(self, "_aviso_facial_sin_modulo", False):
                            self._aviso_facial_sin_modulo = True
                            print(
                                "AVISO: el paquete 'face_recognition' no está instalado. "
                                "En Windows instale dependencias o use el flujo por código (Enter / botón Ingresar con validación 102). "
                                "En Jetson: pip install face_recognition (y dlib)."
                            )
                            self.font.setPointSize(14)
                            self.labelMessage.setFont(self.font)
                            self.labelMessage.setGeometry(
                                self.x + 10, self.y + 300, 500, 80
                            )
                            self.labelMessage.setAlignment(Qt.AlignCenter)
                            self.labelMessage.setText(
                                "Reconocimiento facial no disponible.\n"
                                "Use código + Enter o instale face_recognition."
                            )
                            self.labelMessage.setVisible(True)
                    else:
                        val = self.Encode_Camera(self.image)
                        if val != -2:
                            self.coincidencias += val
                        if val == 0 and self.coincidencias < self.matchCounter and self.coincidencias > self.matchCounter*-1:


                            self.font.setPointSize(12)
                            self.labelMessage.setFont(self.font)
                            self.labelMessage.setText("Coloca tu rostro en el recuadro")
                        if int((100 / (self.matchCounter * self.matchCounter)) * int(abs(self.coincidencias)*self.matchCounter)) >= self.progress:
                            self.progress = int((100 / (self.matchCounter * self.matchCounter)) * int(abs(self.coincidencias)*self.matchCounter))
                            self.progressBar.setValue(self.progress)
                        print('coincidencias ', self.coincidencias)
                        print('muestras ', self.muestras)
                        if (self.coincidencias >= int(self.matchCounter*0.25) or self.coincidencias <= int(self.matchCounter*-0.25)) and self.muestras < int(self.matchCounter*0.75):
                            self.font.setPointSize(25)
                            self.labelMessage.setFont(self.font)
                            self.labelMessage.setText("Procesando")
                            self.bandera = False
                        elif self.coincidencias >= self.matchCounter and self.bandera == False:
                            self.AccesoConcedido(False)
                        elif self.coincidencias == self.matchCounter*-1 or (self.muestras >= int(self.matchCounter*1.5) and self.coincidencias < self.matchCounter):
                        
                            audio_Denegado = "Denegado.mp3"
                            _reproducir_audio_mp3(audio_Denegado)
                            self.font.setPointSize(25)
                            self.labelMessage.setFont(self.font)
                            self.progressBar.setValue(100)
                            self.imgLabel_2.setPixmap(self.AccessDenied)
                            self.imgLabel_2.setStyleSheet('background-color: rgba(255, 0, 0, 0.2);')
                            self.imgLabel_2.setVisible(True)
                            self.labelMessage.setText("Acceso Denegado")
                            QTimer.singleShot(500, self.initialUI)
                else:
                    None
            except Exception as e:
                print(f"Error al actualizar el fotograma: {e}")
        else:
            if MODE != "test":
                self.ESP32()

    def displayImage(self, image, window=1):
        #print("displayImage")
        # Coordenadas de recorte
        y_start, y_end = 50, 530
        x_start, x_end = 50, 410
        # Recortar la imagen
        image = image[y_start:y_end, x_start:x_end]
        # Cambiar el tamaño de la imagen
        image = cv2.resize(image, (640, 480))
        qformat = QImage.Format_Indexed8
        if len(image.shape) == 3:
            if image.shape[2] == 4:
                qformat = QImage.Format_RGBA8888
            else:
                qformat = QImage.Format_RGB888
        outImage = QImage(image, image.shape[1], image.shape[0], image.strides[0], qformat)
        outImage = outImage.rgbSwapped()

        if window == 1:
            self.imgLabel.setPixmap(QPixmap.fromImage(outImage))
            self.imgLabel.setScaledContents(True)

    def correctID(self):
        print("correctID")
        self.imgLabel_3.setVisible(True)
        self.imgLabel_5.setVisible(False)
        self.imgLabel_2.setVisible(False)
        self.labelCodigo.setVisible(False)
        self.imgLabel.setVisible(True)
        self.labelMessage.setText("Codigo correcto")
        self.lineEdit.setEnabled(False)
        self.lineEdit.setVisible(False)
        self.progressBar.setValue(0)
        self.progressBar.setVisible(True)
        print(self.main_route, 'EncodeFile_'+ str(self.ID) + '.p')
        file = open(os.path.join(self.main_route, 'EncodeFile_'+ str(self.ID) + '.p'), 'rb')
        self.encodeListKnownWithIds = pickle.load(file)
        file.close()
        self.encodeListKnown, self.studentIds = self.encodeListKnownWithIds

    def incorrectID(self):
        print("incorrectID")
        audio_Denegado = "Denegado.mp3"
        _reproducir_audio_mp3(audio_Denegado)
        self.labelCodigo.setVisible(False)
        self.lineEdit.setVisible(False)
        self.lineEdit.setVisible(False)
        self.labelMessage.setVisible(True)
        self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
        self.labelMessage.setText("Codigo incorrecto")
        QTimer.singleShot(1000, self.initialUI)


    def initialUI(self):
        print("initialUI")
        if os.path.exists(self.main_route):
            shutil.rmtree(self.main_route)
        self.font.setPointSize(25)
        self.labelMessage.setFont(self.font)
        self.x= 10#int((self.sizeWindow.width()/2)-400)
        self.y= 0#int((self.sizeWindow.height()/2)-350)
        self.imgLabel_5.setVisible(True)
        self.imgLabel_5.setGeometry(self.x + 90, self.y + 50,250,350)
        self.imgLabel_4.setVisible(False)
        self.imgLabel_4.setGeometry(self.x + 550, self.y + 150, 200, 300)
        self.imgLabel_3.setStyleSheet('background-color: rgba(0, 0, 0, 0);')
        self.imgLabel_3.setVisible(False)
        self.imgLabel_3.setGeometry(self.x + 0, self.y + 0,400,400)
        self.imgLabel_3.lower()
        self.imgLabel_2.setStyleSheet('background-color: rgba(0, 0, 0, 0);')
        self.imgLabel_2.setVisible(False)
        self.imgLabel_2.setGeometry(self.x + 42, self.y + 70,320,240) #se modifica tambien en CorrectID()
        self.imgLabel.setGeometry(self.x + 42, self.y + 70,320,240)
        self.imgLabel.setVisible(False)
        self.labelCodigo.setAlignment(Qt.AlignCenter)
        self.labelCodigo.setGeometry(self.x + 10, self.y + 400,400,61) #150x justo
        self.labelCodigo.setVisible(True)
        self.labelMessage.setGeometry(self.x + 10, self.y + 300, 400, 61)
        self.labelMessage.setVisible(False)
        self.labelMessage.setAlignment(Qt.AlignCenter)
        self.hour.setVisible(False)
        self.hour.setGeometry(self.x + 400, self.y + 50, 175, 35)
        self.hourData.setVisible(True)
        self.hourData.setGeometry(self.x + 400, self.y + 50, 500, 35)
        self.date.setVisible(False)
        self.date.setGeometry(self.x + 400, self.y + 10, 175, 35)
        self.dateData.setVisible(True)
        self.dateData.setGeometry(self.x + 400, self.y + 10, 500, 35)
        self.lineEdit.setGeometry(self.x + 100, self.y + 450, 230, 45)
        self.lineEdit.setVisible(True)
        self.lineEdit.setEnabled(True)
        self.lineEdit.clear()
        self.lineEdit.setFocus()
        self.pushButton.setGeometry(self.x + 750, self.y + 400, 150, 100)
        self.pushButton.setVisible(True)
        self.progressBar.setValue(0)
        self.progressBar.setGeometry(self.x + 50, self.y + 400, 300, 45)
        self.progressBar.setVisible(False)
        self.B1.setGeometry(self.x + 450, self.y + 100, 150, 100)
        self.B2.setGeometry(self.x + 600, self.y + 100, 150, 100)
        self.B3.setGeometry(self.x + 750, self.y + 100, 150, 100)
        self.B4.setGeometry(self.x + 450, self.y + 200, 150, 100)
        self.B5.setGeometry(self.x + 600, self.y + 200, 150, 100)
        self.B6.setGeometry(self.x + 750, self.y + 200, 150, 100)
        self.B7.setGeometry(self.x + 450, self.y + 300, 150, 100)
        self.B8.setGeometry(self.x + 600, self.y + 300, 150, 100)
        self.B9.setGeometry(self.x + 750, self.y + 300, 150, 100)
        self.limpiar.setGeometry(self.x + 450, self.y + 400, 150, 100)
        self.limpiar.setVisible(False)
        self.B0.setGeometry(self.x + 600, self.y + 400, 150, 100)
        self.borrar.setGeometry(self.x + 450, self.y + 400, 150, 100)
        self.ID = None
        self.SearchID = 1
        self.coincidencias = 0
        self.muestras = 0
        self.progress = 0
        self.bandera = False
        self.lector = 0
        self.torniquete = False
        self.registroId = None
        self._aviso_facial_sin_modulo = False

    def AccesoConcedido(self, admin):
        self.font.setPointSize(25)
        self.labelMessage.setFont(self.font)
        if admin == True :#or self.lector == 2:
            self.lineEdit.setVisible(False)
            self.imgLabel_5.setVisible(False)
            self.labelCodigo.setVisible(False)
            self.labelMessage.setVisible(True)
            self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
            self.labelMessage.setText("Admin")
            print('Admin')
        if self.lector == 1:
            tipo_tid = (
                self._sga.tipo_ingreso_rfid
                if getattr(self, "_entrada_desde_rf", False)
                else self._sga.tipo_ingreso_teclado
            )
            respuesta, ok = registrar_entrada_http(self._sga, str(self.ID), tipo_tid)
            if respuesta is not None:
                print(respuesta.status_code, getattr(respuesta, "text", "")[:300])
            if ok:
                print("AccesoCondedido")
                audio_Acceso = "Acceso.mp3"
                _reproducir_audio_mp3(audio_Acceso)
                self.bandera = True
                self.imgLabel_2.setPixmap(self.AccessGranted)
                self.imgLabel_2.setStyleSheet('background-color: rgba(0, 255, 0, 0.2);')
                self.imgLabel_2.setVisible(True)
                self.labelMessage.setText("Entrada")
                self._enviar_torniquete_entrada()
            else:
                print('error')
                self.labelMessage.setText("Error para Entrar")
        elif self.lector == 2:
            tipo_tid = (
                self._sga.tipo_ingreso_rfid
                if getattr(self, "_salida_desde_rf", False)
                else self._sga.tipo_ingreso_teclado
            )
            rid = getattr(self, "registroId", None)
            print("Salida registroId=", rid)
            respuesta = None
            ok = False
            try:
                if rid is None:
                    raise ValueError("registroId requerido para salida")
                respuesta, ok = registrar_salida_http(
                    self._sga, int(rid), tipo_tid
                )
            except (ValueError, TypeError) as e:
                print("Error salida SGACCUV:", e)
                ok = False
            if respuesta is not None:
                print(respuesta.status_code, getattr(respuesta, "text", "")[:300])
            if ok:
                self.lineEdit.setVisible(False)
                self.imgLabel_5.setVisible(False)
                self.labelCodigo.setVisible(False)
                self.labelMessage.setVisible(True)
                self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
                print("AccesoCondedido")
                audio_Acceso = "Acceso.mp3"
                _reproducir_audio_mp3(audio_Acceso)
                self.bandera = True
                self.imgLabel_2.setPixmap(self.AccessGranted)
                self.imgLabel_2.setStyleSheet('background-color: rgba(0, 255, 0, 0.2);')
                self.imgLabel_2.setVisible(True)
                self.labelMessage.setText("Salida")
                self._enviar_torniquete_salida()
            else:
                print('error')
                self.imgLabel_5.setVisible(False)
                self.labelCodigo.setVisible(False)
                self.lineEdit.setVisible(False)
                self.labelMessage.setVisible(True)
                self.labelMessage.setText("Error para Salir")
        QTimer.singleShot(500, self.initialUI)

    def ESP32(self):
        print('ESP32')
        if MODE == "test":
            print("MODE=test: se omite apertura del puerto serial (ESP32).")
            return
        try:
            
            self.ser = serial.Serial('/dev/ttyUSB0', 9600)
            #self.ser = serial.Serial('COM6', 9600)
            self.lectores = True
            self.initialUI()
        except serial.SerialException as e:
            print("Lectores no conectados")
            #print(f"Error al abrir el puerto serial: {e}")
            self.lectores = False
            self.font.setPointSize(21)
            self.labelMessage.setFont(self.font)
            self.labelMessage.setAlignment(Qt.AlignCenter)
            self.labelMessage.setGeometry(self.x + 10, self.y + 400, 400, 61)
            self.labelMessage.setText("Lectores no disponibles")
            self.labelMessage.setVisible(True)
            self.labelCodigo.setVisible(False)
            self.lineEdit.setVisible(False)
            self.lineEdit.setEnabled(False)







if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = Ui_OutputDialog()
    ui.show()
    sys.exit(app.exec_())
