from __future__ import annotations

from pathlib import Path


class OpenCVCamera:
    def __init__(self, index: int) -> None:
        self.index = index
        self._cap = None

    def __enter__(self):
        self._cap = self._open()
        return self

    def __exit__(self, *_exc) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def capture(self, path: Path) -> Path:
        frame = self.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2 = self._cv2()
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"could not write {path}")
        return path

    def read(self):
        cap = self._cap or self._open()
        try:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"camera {self.index} did not return a frame")
            return frame
        finally:
            if self._cap is None:
                cap.release()

    def _open(self):
        cv2 = self._cv2()
        for backend in camera_backends(cv2):
            cap = cv2.VideoCapture(self.index, backend)
            if cap.isOpened():
                return cap
            cap.release()
        raise RuntimeError(f"camera {self.index} did not open")

    @staticmethod
    def _cv2():
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python is not installed") from exc
        return cv2


def camera_backends(cv2):
    return tuple(
        backend
        for backend in (
            getattr(cv2, "CAP_DSHOW", None),
            getattr(cv2, "CAP_MSMF", None),
            getattr(cv2, "CAP_ANY", 0),
        )
        if backend is not None
    )
