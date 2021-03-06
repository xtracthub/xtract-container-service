import docker
import threading
import time
import uuid
from container_handler import build_container, repo2docker_container
from sqs_queue_utils import get_message


class TaskManager:
    """Manager for threads and various container building tasks.

    Parameters:
    max_threads (int): Maximum number of threads to run.
    idle_time (int): Time to wait before idling a thread.
    kill_time (int): Time to wait before killing a thread.
    max_retry (int): Max number of retries for a function.

    Attributes:
    max_threads (int): Maximum number of threads to run.
    idle_time (int): Time to wait before idling a thread.
    kill_time (int): Time to wait before killing a thread.
    max_retry (int): Max number of retries for a function.
    total_threads (int): The number of currently running threads.
    pruning (bool): Whether a pruning job is currently running.
    """
    def __init__(self, max_threads=5, kill_time=180, max_retry=1):
        print(self)
        self.max_threads = max_threads
        self.kill_time = kill_time
        self.max_retry = max_retry
        self.thread_status = {"hello": "k"}
        self.total_threads = 0
        self.pruning = False

    def execute_work(self):
        """Pulls down a message from SQS and performs a task. Automatically
        dies when it hasn't performed a task in self.kill_time seconds.
        """
        thread_id = str(uuid.uuid4())
        self.thread_status[thread_id] = "WORKING"
        start_time = time.time()
        while True:
            if time.time() - start_time >= self.kill_time:
                break
            elif not self.pruning:
                task = get_message()
                if task is not None:
                    self.thread_status[thread_id] = "WORKING"
                    function_name = task.pop("function_name")

                    args = []
                    for arg in task:
                        args.append(task[arg])

                    if function_name == "build_container":
                        attempt_num = 0
                        while attempt_num <= self.max_retry:
                            try:
                                build_container(*args)
                                break
                            except:
                                attempt_num += 1
                    elif function_name == "repo2docker_container":
                        repo2docker_container(*args)
                    else:
                        break
                    start_time = time.time()
                else:
                    self.thread_status[thread_id] = "IDLE"
                    continue

            time.sleep(5)

        self.total_threads -= 1
        del self.thread_status[thread_id]
        return

    def prune_task(self, prune_time):
        """Task that periodically runs pruning commands.

        Parameters:
        prune_time (int): Amount of time to wait before pruning containers.
        """
        thread_id = f"PRUNE_THREAD_{str(uuid.uuid4())}"
        self.thread_status[thread_id] = "IDLE"
        client = docker.from_env()

        while True:
            if any([self.thread_status[thread] == "WORKING" for thread in self.thread_status]):
                time.sleep(prune_time)
            else:
                self.thread_status[thread_id] = "WORKING"
                self.pruning = True
                client.images.prune()
                self.pruning = False
                self.thread_status[thread_id] = "IDLE"
                time.sleep(prune_time)

    def start_prune_thread(self, prune_time):
        """Starts a daemon thread running the prune_task method.

        Parameters:
        prune_time (int): Amount of time to wait before pruning containers.
        """
        threading.Thread(target=self.prune_task, args=(prune_time,), daemon=True).start()

    def start_thread(self):
        """Starts a thread to do work.
        """
        if self.total_threads < self.max_threads:
            threading.Thread(target=self.execute_work).start()
            self.total_threads += 1
