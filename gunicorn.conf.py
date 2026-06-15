import multiprocessing

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
workers = (2 * multiprocessing.cpu_count()) + 1
timeout = 120
keepalive = 5
