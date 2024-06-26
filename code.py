import os
import random
import argparse
from PIL import Image
from typing import Union
import bbox
import abc
import dataclasses
import torch
from torchvision import transforms
from ultralytics import YOLO

@dataclasses.dataclass
class ClassifierOutput:
    class_: str
    conf: float

class Classifier:
    def __init__(self, transform: transforms.Compose = None):
        self.transform = transform

    @abc.abstractmethod
    def classify(self, image: Union[Image.Image, str]) -> ClassifierOutput:
        pass

class YoloClassifier(Classifier):
    def __init__(self, model_path: str, **kwargs):
        super().__init__()
        self._model = YOLO(model_path)
        self._device = kwargs.pop("device", "cpu")
        self._batch_size = kwargs.pop("batch", 16)  # Default batch size to 16
        self._resize = kwargs.pop("resize", (640, 640))  # Default resize to 640x640
        print(f"Model initialized with batch size {self._batch_size} on device {self._device}")

    def classify(self, image: Union[Image.Image, str]) -> ClassifierOutput:
        if isinstance(image, Image.Image):
            transform = transforms.Compose([
                transforms.Resize(self._resize),
                transforms.ToTensor()
            ])
            image = transform(image).unsqueeze(0)  # Ensure image is a batch of one
        image = image.to(self._device if isinstance(self._device, torch.device) else torch.device(self._device))
        
        result = self._model(image, verbose=False, device=self._device, batch=self._batch_size)  # Use the batch size
        print(f"Running model on device {self._device} with batch size {self._batch_size}")
        if not result or len(result) == 0:
            raise ValueError("Model did not return any results.")
        return ClassifierOutput(result[0].names[result[0].probs.top1], result[0].probs.top1conf)

from bbox import BBox2D, XYXY

def crop(img: Image.Image, bbox: BBox2D):
    return img.crop((int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)))

def iou(b1: BBox2D, b2: BBox2D) -> float:
    x_a = max(b1.x1, b2.x1)
    y_a = max(b1.y1, b2.y1)
    x_b = min(b1.x2, b2.x2)
    y_b = min(b1.y2, b2.y2)
    inter_area = max(0, x_b - x_a) * max(0, y_b - y_a)
    box_a_area = (b1.x2 - b1.x1) * (b1.y2 - b1.y1)
    box_b_area = (b2.x2 - b2.x1) * (b2.y2 - b2.y1)
    denominator = float(box_a_area + box_b_area - inter_area)
    return inter_area / denominator if denominator != 0 else 0

def find_closest_iou(b1: BBox2D, contenders: list[BBox2D]):
    last_i, last_iou = 0, iou(b1, contenders[0])
    for idx, c in enumerate(contenders[1:]):
        new_iou = iou(b1, c)
        if new_iou > last_iou:
            last_i, last_iou = idx + 1, new_iou
    return last_i, last_iou

def from_yolo_bbox(cx, cy, nw, nh, w, h) -> BBox2D:
    left = max(0, int((cx - nw / 2) * w))
    upper = max(0, int((cy - nh / 2) * h))
    right = min(w, int((cx + nw / 2) * w))
    lower = min(h, int((cy + nh / 2) * h))
    return BBox2D((left, upper, right, lower), mode=XYXY)

def distort(x1, y1, x2, y2):
    w = x2 - x1
    h = y2 - y1
    max_distortion_x = 0.6 * w
    max_distortion_y = 0.6 * h
    distortion_x = random.uniform(0, max_distortion_x)
    distortion_y = random.uniform(0, max_distortion_y)
    distortion_x = random.choice([-1, 1]) * distortion_x
    distortion_y = random.choice([-1, 1]) * distortion_y
    x1_distorted = int(max(0, x1 + distortion_x))
    y1_distorted = int(max(0, y1 + distortion_y))
    x2_distorted = int(min(w, x2 + distortion_x))
    y2_distorted = int(min(h, y2 + distortion_y))
    return x1_distorted, y1_distorted, x2_distorted, y2_distorted

def distort_image(img: Image.Image) -> tuple[float, Image.Image]:
    w, h = img.size
    x1, y1, x2, y2 = 0, 0, w - 1, h - 1
    old_bbox = bbox.BBox2D((x1, y1, x2, y2), mode=bbox.XYXY)
    x1, y1, x2, y2 = distort(x1, y1, x2, y2)
    new_bbox = bbox.BBox2D((x1, y1, x2, y2), mode=bbox.XYXY)
    _iou = iou(old_bbox, new_bbox)
    return _iou, img.crop((x1, y1, x2, y2))

def main(dir_: str, classifier: YoloClassifier):
    d = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0}
    d_not = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0}

    for cls_dir in os.listdir(dir_):
        for file in os.listdir(f"{dir_}/{cls_dir}"):
            if file.endswith(".png"):
                img = Image.open(f"{dir_}/{cls_dir}/{file}")
                _iou, img = distort_image(img)
                print(f"Processing file: {file}, IoU: {_iou}")

                try:
                    pred = classifier.classify(img).class_
                    print(f"Prediction: {pred}, Actual: {cls_dir}")
                except Exception as e:
                    print(f"Error classifying image {file}: {e}")
                    continue

                if _iou < 0.2:
                    d[2] += pred == cls_dir
                    d_not[2] += pred != cls_dir
                elif _iou < 0.3:
                    d[3] += pred == cls_dir
                    d_not[3] += pred != cls_dir
                elif _iou < 0.4:
                    d[4] += pred == cls_dir
                    d_not[4] += pred != cls_dir
                elif _iou < 0.5:
                    d[5] += pred == cls_dir
                    d_not[5] += pred != cls_dir
                elif _iou < 0.6:
                    d[6] += pred == cls_dir
                    d_not[6] += pred != cls_dir
                elif _iou < 0.7:
                    d[7] += pred == cls_dir
                    d_not[7] += pred != cls_dir
                elif _iou < 0.8:
                    d[8] += pred == cls_dir
                    d_not[8] += pred != cls_dir
                elif _iou < 0.9:
                    d[9] += pred == cls_dir
                    d_not[9] += pred != cls_dir
                else:
                    d[10] += pred == cls_dir
                    d_not[10] += pred != cls_dir

    print(d)
    print(d_not)

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description='Infer a model')
    arg_parser.add_argument('--classifier', type=str, required=True, choices=["yolon", "yolos", "yolom", "yolol"],
                            help='classifier')
    arg_parser.add_argument('--dataset', type=str, required=True, choices=["shvn", "coco-animal"], help='classifier')
    arg_parser.add_argument('--device', type=str, required=True, choices=["cpu", "gpu"], help='device')
    arg_parser.add_argument('--batch', type=int, default=16, help='batch size for inference')

    args = arg_parser.parse_args()

    device = 'cpu' if args.device == 'cpu' else torch.device("cuda")

    classifier = args.classifier
    if classifier == "yolon":
        classifier = YoloClassifier(f"/home/astha/vizq-experiment/vizq-experiment-master/train/vizq-exp-models/yolon-cls-{args.dataset}.pt", device=device, batch=args.batch)
    elif classifier == "yolos":
        classifier = YoloClassifier(f"train/vizq-exp-models/yolos-cls-{args.dataset}.pt", device=device, batch=args.batch)
    elif classifier == "yolom":
        classifier = YoloClassifier(f"train/vizq-exp-models/yolom-cls-{args.dataset}.pt", device=device, batch=args.batch)
    elif classifier == "yolol":
        classifier = YoloClassifier(f"train/vizq-exp-models/yolol-cls-{args.dataset}.pt", device=device, batch=args.batch)
    else:
        raise Exception("Unrecognized classifier")

    main("/home/astha/vizq-experiment/vizq-experiment-master/dataset/shvn/digits/val", classifier)
