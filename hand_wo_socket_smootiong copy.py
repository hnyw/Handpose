import socket
import sys
import cv2
import cv2 as cv
import copy
import csv
import mediapipe as mp
import numpy as np
import struct
import matplotlib.pyplot as plt
import itertools

from pandas import DataFrame
from collections import Counter
from collections import deque
from utils import CvFpsCalc
from model import KeyPointClassifier
from model import PointHistoryClassifier

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_hands = mp.solutions.hands

Wr = 0
M0 = 9
M3 = 12

Wr = 0
firstF = [1,2,3,4]
secondF = [5,6,7,8]
middleF = [9,10,11,12]
ringF = [13,14,15,16]
pinkyF= [17,18,19,20]

fingerList = [firstF,secondF,middleF,ringF,pinkyF]

Queue = []
CONF_THRESHOLD = 0.6
Q_NUM =5
pre_List =[]
HOST="192.168.0.110" # 192.168.0.11: 기숙사,  192.168.0.40: 연구실
PORT=8888
successframe = 0 # success한 frame 개수가 몇개인지 판단.

preMatrix = np.empty((12,3))
curMatrix = np.empty((12,3))
moveMatrix = np.zeros((12,3))
confidence = np.zeros((2))

keypoint_classifier = KeyPointClassifier()

point_history_classifier = PointHistoryClassifier()



# Read labels ###########################################################
with open('model/keypoint_classifier/keypoint_classifier_label.csv',
            encoding='utf-8-sig') as f:
    keypoint_classifier_labels = csv.reader(f)
    keypoint_classifier_labels = [
        row[0] for row in keypoint_classifier_labels
    ]
with open(
        'model/point_history_classifier/point_history_classifier_label.csv',
        encoding='utf-8-sig') as f:
    point_history_classifier_labels = csv.reader(f)
    point_history_classifier_labels = [
        row[0] for row in point_history_classifier_labels
    ]

# FPS Measurement ########################################################
cvFpsCalc = CvFpsCalc(buffer_len=10)

# Coordinate history #################################################################
history_length = 16
point_history = deque(maxlen=history_length)

# Finger gesture history ################################################
finger_gesture_history = deque(maxlen=history_length)

#  ########################################################################
mode = 0

hand_sign_id = -1
isStart = False

def reset():
    isStart = False
    Queue = []
    successframe = 0 # success한 frame 개수가 몇개인지 판단.
    preMatrix = np.empty((12,3))
    curMatrix = np.empty((12,3))
    moveMatrix = np.zeros((12,3))
    confidence = np.zeros((2))
    point_history = deque(maxlen=history_length)
    hand_sign_id = -1
    finger_gesture_history = deque(maxlen=history_length)

def n_vector(list1, list2):
    fvector = list1-list2
    x,y,z = fvector
    norm = (x**2+y**2+z**2)**(1/2)
    return [x/norm, y/norm, z/norm]


def vector_movement(moveMatrix, successframe, preMatrix, curMatrix):

    curmove = abs(curMatrix - preMatrix)
    moveMatrix = moveMatrix + ((curmove-moveMatrix)/successframe)

    return moveMatrix

def calculate_final(moveMatrix,preMatrix,curMatrix,confidence,successframe):

    # single point prediction update 
    posMatrix = np.zeros((12,3))
    for j, pPoint in enumerate(zip(preMatrix,curMatrix)):
        for i in range(3):
            if  pPoint[1][i] >pPoint[0][i] :
                posMatrix[j][i] = 1
            else:
                posMatrix[j][i] = -1

    # position = np.array([ 1 if i >j else -1  for cjoint, pjoint in enumerate(zip(preMatrix,curMatrix)) for i, j in enumerate(zip(cjoint, pjoint))])
    predict = moveMatrix*posMatrix + preMatrix 

    # Compare current vector and predict vector and update
    curMatrix = (predict * confidence[0] + curMatrix * confidence[1]) / (confidence[0]+confidence[1])

    moveMatrix = vector_movement(moveMatrix,successframe,predict,curMatrix) # Single movement vector update

    confidence[0] = (confidence[1]*confidence[0])/(confidence[1] + confidence[0])

    preMatrix = curMatrix

def make_numpy(hand_handedness):
    fingerlist = [1,2,3,4,5,6,7,8,9,10,11,12]
    point = []
    for i in fingerlist:
        fingerPoint = [hand_handedness[i].x,hand_handedness[i].y,hand_handedness[i].z]
        point.append(fingerPoint)
    return np.array(point)


def calc_bounding_rect(image, landmarks):
    image_width, image_height = image.shape[1], image.shape[0]

    landmark_array = np.empty((0, 2), int)

    for _, landmark in enumerate(landmarks.landmark):
        landmark_x = min(int(landmark.x * image_width), image_width - 1)
        landmark_y = min(int(landmark.y * image_height), image_height - 1)

        landmark_point = [np.array((landmark_x, landmark_y))]

        landmark_array = np.append(landmark_array, landmark_point, axis=0)

    x, y, w, h = cv.boundingRect(landmark_array)

    return [x, y, x + w, y + h]


def calc_landmark_list(image, landmarks):
    image_width, image_height = image.shape[1], image.shape[0]

    landmark_point = []

    # Keypoint
    for _, landmark in enumerate(landmarks.landmark):
        landmark_x = min(int(landmark.x * image_width), image_width - 1)
        landmark_y = min(int(landmark.y * image_height), image_height - 1)
        # landmark_z = landmark.z

        landmark_point.append([landmark_x, landmark_y])

    return landmark_point


def pre_process_landmark(landmark_list):
    temp_landmark_list = copy.deepcopy(landmark_list)

    # Convert to relative coordinates
    base_x, base_y = 0, 0
    for index, landmark_point in enumerate(temp_landmark_list):
        if index == 0:
            base_x, base_y = landmark_point[0], landmark_point[1]

        temp_landmark_list[index][0] = temp_landmark_list[index][0] - base_x
        temp_landmark_list[index][1] = temp_landmark_list[index][1] - base_y

    # Convert to a one-dimensional list
    temp_landmark_list = list(
        itertools.chain.from_iterable(temp_landmark_list))

    # Normalization
    max_value = max(list(map(abs, temp_landmark_list)))

    def normalize_(n):
        return n / max_value

    temp_landmark_list = list(map(normalize_, temp_landmark_list))

    return temp_landmark_list


def pre_process_point_history(image, point_history):
    image_width, image_height = image.shape[1], image.shape[0]

    temp_point_history = copy.deepcopy(point_history)

    # Convert to relative coordinates
    base_x, base_y = 0, 0
    for index, point in enumerate(temp_point_history):
        if index == 0:
            base_x, base_y = point[0], point[1]

        temp_point_history[index][0] = (temp_point_history[index][0] -
                                        base_x) / image_width
        temp_point_history[index][1] = (temp_point_history[index][1] -
                                        base_y) / image_height

    # Convert to a one-dimensional list
    temp_point_history = list(
        itertools.chain.from_iterable(temp_point_history))

    return temp_point_history


def draw_landmarks(image, landmark_point):
    if len(landmark_point) > 0:
        # Thumb
        cv.line(image, tuple(landmark_point[2]), tuple(landmark_point[3]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[2]), tuple(landmark_point[3]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[3]), tuple(landmark_point[4]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[3]), tuple(landmark_point[4]),
                (255, 255, 255), 2)

        # Index finger
        cv.line(image, tuple(landmark_point[5]), tuple(landmark_point[6]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[5]), tuple(landmark_point[6]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[6]), tuple(landmark_point[7]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[6]), tuple(landmark_point[7]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[7]), tuple(landmark_point[8]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[7]), tuple(landmark_point[8]),
                (255, 255, 255), 2)

        # Middle finger
        cv.line(image, tuple(landmark_point[9]), tuple(landmark_point[10]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[9]), tuple(landmark_point[10]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[10]), tuple(landmark_point[11]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[10]), tuple(landmark_point[11]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[11]), tuple(landmark_point[12]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[11]), tuple(landmark_point[12]),
                (255, 255, 255), 2)

        # Ring finger
        cv.line(image, tuple(landmark_point[13]), tuple(landmark_point[14]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[13]), tuple(landmark_point[14]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[14]), tuple(landmark_point[15]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[14]), tuple(landmark_point[15]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[15]), tuple(landmark_point[16]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[15]), tuple(landmark_point[16]),
                (255, 255, 255), 2)

        # Little finger
        cv.line(image, tuple(landmark_point[17]), tuple(landmark_point[18]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[17]), tuple(landmark_point[18]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[18]), tuple(landmark_point[19]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[18]), tuple(landmark_point[19]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[19]), tuple(landmark_point[20]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[19]), tuple(landmark_point[20]),
                (255, 255, 255), 2)

        # Palm
        cv.line(image, tuple(landmark_point[0]), tuple(landmark_point[1]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[0]), tuple(landmark_point[1]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[1]), tuple(landmark_point[2]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[1]), tuple(landmark_point[2]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[2]), tuple(landmark_point[5]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[2]), tuple(landmark_point[5]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[5]), tuple(landmark_point[9]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[5]), tuple(landmark_point[9]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[9]), tuple(landmark_point[13]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[9]), tuple(landmark_point[13]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[13]), tuple(landmark_point[17]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[13]), tuple(landmark_point[17]),
                (255, 255, 255), 2)
        cv.line(image, tuple(landmark_point[17]), tuple(landmark_point[0]),
                (0, 0, 0), 6)
        cv.line(image, tuple(landmark_point[17]), tuple(landmark_point[0]),
                (255, 255, 255), 2)

    # Key Points
    for index, landmark in enumerate(landmark_point):
        if index == 0:  # 手首1
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 1:  # 手首2
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 2:  # 親指：付け根
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 3:  # 親指：第1関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 4:  # 親指：指先
            cv.circle(image, (landmark[0], landmark[1]), 8, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 8, (0, 0, 0), 1)
        if index == 5:  # 人差指：付け根
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 6:  # 人差指：第2関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 7:  # 人差指：第1関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 8:  # 人差指：指先
            cv.circle(image, (landmark[0], landmark[1]), 8, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 8, (0, 0, 0), 1)
        if index == 9:  # 中指：付け根
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 10:  # 中指：第2関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 11:  # 中指：第1関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 12:  # 中指：指先
            cv.circle(image, (landmark[0], landmark[1]), 8, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 8, (0, 0, 0), 1)
        if index == 13:  # 薬指：付け根
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 14:  # 薬指：第2関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 15:  # 薬指：第1関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 16:  # 薬指：指先
            cv.circle(image, (landmark[0], landmark[1]), 8, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 8, (0, 0, 0), 1)
        if index == 17:  # 小指：付け根
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 18:  # 小指：第2関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 19:  # 小指：第1関節
            cv.circle(image, (landmark[0], landmark[1]), 5, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 5, (0, 0, 0), 1)
        if index == 20:  # 小指：指先
            cv.circle(image, (landmark[0], landmark[1]), 8, (255, 255, 255),
                      -1)
            cv.circle(image, (landmark[0], landmark[1]), 8, (0, 0, 0), 1)

    return image


def draw_bounding_rect(use_brect, image):

    return image


def draw_info_text(image, brect, handedness, hand_sign_text,
                   finger_gesture_text):
    cv.rectangle(image, (brect[0], brect[1]), (brect[2], brect[1] - 22),
                 (0, 0, 0), -1)

    info_text = handedness.classification[0].label[0:]
    if hand_sign_text != "":
        info_text = info_text + ':' + hand_sign_text
    cv.putText(image, info_text, (brect[0] + 5, brect[1] - 4),
               cv.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv.LINE_AA)

    if finger_gesture_text != "":
        cv.putText(image, "Finger Gesture:" + finger_gesture_text, (10, 60),
                   cv.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4, cv.LINE_AA)
        cv.putText(image, "Finger Gesture:" + finger_gesture_text, (10, 60),
                   cv.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2,
                   cv.LINE_AA)

    return image


def draw_point_history(image, point_history):
    for index, point in enumerate(point_history):
        if point[0] != 0 and point[1] != 0:
            cv.circle(image, (point[0], point[1]), 1 + int(index / 2),
                      (152, 251, 152), 2)

    return image




with mp_hands.Hands(
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5) as hands:
    
    framenum = 0
    isFirst = True
    cap = cv2.VideoCapture(0)
    isStart = True
    while cap.isOpened():
        framenum = framenum+1
        success, image = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            # If loading a video, use 'break' instead of 'continue'.
            continue

        # To improve performance, optionally mark the image as not writeable to
        # pass by reference.
        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = hands.process(image)

        # Draw the hand annotations on the image.
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        gimage = cv.flip(image, 1)

        if (results.multi_hand_landmarks and results.multi_hand_world_landmarks):
            # print(len(results.multi_handedness))
            Queue.append([results.multi_handedness, results.multi_hand_landmarks, results.multi_hand_world_landmarks])
        else:
            Queue.append(None)
    
        if len(Queue) > Q_NUM:
            q = Queue.pop(0)
            
            if(isFirst == True):
                pre_List.append(q)
                pre_List.append(q)
            pre_q = pre_List[0]
            move = pre_List[1]
            
            if(q is None or len(q)==0):
                for i in Queue:
                    isFail = False
                    if(i is not None):
                        isFail = True
                        break
                if(isFail):
                    q = pre_q
            if q and pre_q is not None and len(q)!=0:
                for i, (hand_handedness, hand_landmarks,hand_world_landmarks) in enumerate(zip(q[0],q[1],q[2])):
                    if len(q[0])==1 and hand_handedness.classification[0].score < CONF_THRESHOLD:
                        if pre_q is not None and len(list(pre_q))==1:
                            pre_mlh, pre_hand_landmarks,pre_hand_world_landmarks = pre_q
                            if pre_mlh.classification[0].score >= CONF_THRESHOLD:
                                hand_landmarks = pre_hand_landmarks 
                                hand_world_landmarks = pre_hand_world_landmarks

                    if(hand_handedness.classification[0].label == "Left"):

                        # Bounding box calculation
                        brect = calc_bounding_rect(gimage, hand_world_landmarks)
                        # Landmark calculation
                        landmark_list = calc_landmark_list(gimage, hand_world_landmarks)

                        # Conversion to relative coordinates / normalized coordinates
                        pre_processed_landmark_list = pre_process_landmark(
                            landmark_list)
                        pre_processed_point_history_list = pre_process_point_history(
                            image, point_history)        

                        # Hand sign classification
                        hand_sign_id = keypoint_classifier(pre_processed_landmark_list)

                
                        if(hand_sign_id == 0 and isStart == False):
                            print(hand_sign_id , isStart)
                            Queue = []
                            successframe = 0 # success한 frame 개수가 몇개인지 판단.
                            preMatrix = np.empty((12,3))
                            curMatrix = np.empty((12,3))
                            moveMatrix = np.zeros((12,3))
                            confidence = np.zeros((2))
                            point_history = deque(maxlen=history_length)
                            hand_sign_id = -1
                            finger_gesture_history = deque(maxlen=history_length)
                            isStart = True

                        if isStart == False:
                            print(hand_sign_id , isStart)
                            break

                        if(hand_sign_id == 1):
                            isStart = False
                            break
                        
                        print(hand_sign_id , isStart)
                        if hand_sign_id == 6:  # Point gesture
                            point_history.append(landmark_list[8])
                        else:
                            point_history.append([0, 0])
                        
                        if(hand_sign_id == 2):
                            if(hand_world_landmarks.landmark[0].x - hand_world_landmarks.landmark[8].x > 0 ):
                                direction = 0
                            else:
                                direction = 1

                            print(direction)

                        # Finger gesture classification
                        finger_gesture_id = 0
                        point_history_len = len(pre_processed_point_history_list)
                        if point_history_len == (history_length * 2):
                            finger_gesture_id = point_history_classifier(
                                pre_processed_point_history_list)

                        # Calculates the gesture IDs in the latest detection
                        finger_gesture_history.append(finger_gesture_id)
                        most_common_fg_id = Counter(
                            finger_gesture_history).most_common()

                            # Drawing part
                        gimage = draw_bounding_rect(True, gimage)
                        gimage = draw_landmarks(gimage, landmark_list)
                        gimage = draw_info_text(
                            gimage,
                            brect,
                            hand_handedness,
                            keypoint_classifier_labels[hand_sign_id],
                            point_history_classifier_labels[most_common_fg_id[0][0]],
                        )

                        
                        gimage = draw_point_history(gimage, point_history)
                        cv2.imshow('MediaPipe Hands', cv2.flip(image, 1))

                    if isStart == False:
                        break

                    if(hand_handedness.classification[0].label == "Right"):
                        successframe = successframe+1

                        if successframe == 1 :
                            preMatrix = make_numpy(hand_world_landmarks.landmark)
                            continue
                        curMatrix = make_numpy(hand_world_landmarks.landmark)
                        if successframe == 2:
                            moveMatrix  = vector_movement(moveMatrix, successframe-1, preMatrix, curMatrix)
                            confidence[0] = hand_handedness.classification[0].score 
                            preMatrix = curMatrix
                            continue
                        confidence[1] = hand_handedness.classification[0].score 

                        calculate_final(moveMatrix,preMatrix,curMatrix,confidence,successframe-1)
                        preMatrix = curMatrix

                        lefthandvector = n_vector(curMatrix[0],curMatrix[3])
                        headvector = n_vector(curMatrix[4],curMatrix[7])
                        righthandvector = n_vector(curMatrix[8],curMatrix[11])
                        cv2.putText(image, text="righthand "+str(righthandvector), org=(50,50), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=1, color=(255, 255, 255), thickness=2)
                        cv2.putText(image, text="head "+str(headvector), org=(100,100), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=1, color=(255, 255, 255), thickness=2)
                        cv2.putText(image, text="lefthand "+str(lefthandvector), org=(150,150), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=1, color=(255, 255, 255), thickness=2)


                    # data = struct.pack('<3f',*righthandvector)
                    
                    # print(data.decode("utf-8"))

                    # conn.send(str(righthandvector[0]).encode()+str(righthandvector[1]).encode()+str(righthandvector[2]).encode())
                    # if not results.multi_hand_world_landmarks:

            # if(framenum>100):
            #     pre_List[1] = q
            #     framenum =0
            pre_List[0] = q
            pre_List[1] = q

        # Flip the image horizontally for a selfie-view display.
                    
        if cv2.waitKey(5) & 0xFF == 27:
            # df = DataFrame.from_dict(data)
            # if not os.path.exists('data2.csv'):
            #     df.to_csv('data2.csv', index=False, mode='w')
            # else:
            # df.to_csv('datapoint.csv', index=False, mode='w', header=False)
            break
cap.release()
cv.destroyAllWindows()

