"""One memory-intensive local model operation per gateway process."""
import threading

local_inference_lock = threading.Lock()
