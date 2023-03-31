import os
import traceback
import sys
import io
import argparse
import smtplib
import ssl
import json
import pathlib
import datetime
from email.message import EmailMessage
import logging
import typing
import socket
from multiprocessing import Process, Pipe

class Emailer(object):
    """
    A class for sending an occasional email for debugging & notification purposes.
    Note: This class logs into the SMTP server each time it sends a message.
        Don't use it for sending lots of emails at a time.
    """

    def __init__(self, server, port, username, password, from_email, logger:logging.Logger, subject_prefix='', enabled=True):
        self.smtp_server = server
        self.port = int(port)
        self.username = username
        self.password = password
        self.from_email = from_email
        self.subject_prefix = subject_prefix
        self.enabled = enabled
        self.log = logger
        if self.port == 465:
            self.security = 'SSL'
        elif self.port == 587:
            self.security = 'STARTTLS'
        else:
            self.security = None

    def send(self, subject, to_email, message):
        result = 0

        if self.enabled:
            msg = EmailMessage()
            if self.subject_prefix != '':
                subject = f'{self.subject_prefix}: {subject}'
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg.set_content(message)

            try:

                if self.security == 'SSL':
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(self.smtp_server, self.port, context=context) as server:
                        server.login(self.username, self.password)
                        server.send_message(msg)

                elif self.security == 'STARTTLS':
                    with smtplib.SMTP(self.smtp_server, self.port) as server:
                        server.ehlo()
                        server.starttls()
                        server.login(self.username, self.password)
                        server.send_message(msg)

                else:
                    raise ValueError("No security set for Emailer")

            except smtplib.SMTPServerDisconnected as ex:
                etxt = traceback.print_exc()
                self.log.error(f"::EMAIL ERROR:: Tried to send email, but could not log in to SMTP server: {ex.__class__.__name__}:{ex}")
                result = ex
            except smtplib.SMTPDataError as ex:
                etxt = traceback.print_exc()
                self.log.error(f"::EMAIL ERROR:: Tried to send email, but received data error: {ex.__class__.__name__}:{ex}")
                result = ex
            except socket.gaierror as ex:
                etxt = traceback.print_exc()
                self.log.error(f"::EMAIL ERROR:: Could not resolve SMTP server name: {ex.__class__.__name__}:{ex}")
        else:
            result = "WARNING: Tried to send Email message, but emailer.enabled == False!"
            self.log.warning(result)

        return result



class Transcript(object):
    """
    A class for managing writing JSON objects into timestamped transcripts.

    NOTE: Additions to the transcript are not flushed into the file buffer until
        1. lines_per_flush is exceeded
        2. a new logfile is created
        3. the Transcript is closed
    """

    def __init__(
        self, 
        log_path:typing.Union[str,pathlib.Path], 
        name:str, 
        new_file_on:str='time', 
        lines_per_log:int=1000, 
        time_per_log:str='01:00:00', 
        lines_per_flush:int=100) -> "Transcript":
        
        self.current_file = None
        self.current_line = 0
        self.lines_per_flush = lines_per_flush

        if new_file_on == 'day':
            # New file at midnight
            self.time_per_log = datetime.timedelta(hours=24)

        elif new_file_on == 'lines':
            # New file every lines_per_log
            self.lines_per_log = lines_per_log

        elif new_file_on == 'time':
            # New file every time_per_log HH:MM:SS
            tsegs = time_per_log.split(':')
            self.time_per_log = datetime.timedelta(
                hours=int(tsegs[0]),
                minutes=int(tsegs[1]),
                seconds=int(tsegs[2])
            )
        else:
            raise ValueError(f"Unknown new_file_on value '{new_file_on}'")


        if log_path is None:
            log_path = 'transcripts/'
        self.log_path = pathlib.Path(os.path.abspath(log_path))
        if not self.log_path.exists():
            print(f"Transcripts directory does not exist, making directory: {self.log_path}")
            os.makedirs(self.log_path)

        if name is None:
            name = 'TRANSCRIPT'
        self.name = name
        self.new_file_on = new_file_on
        self.create_new_log()

    def create_new_log(self):

        if self.current_file is not None:
            self.current_file.close()

        if self.new_file_on == 'day':
            self.current_line = 0
            self.log_start = datetime.datetime.combine(datetime.date.today(), datetime.datetime.min.time())
        elif self.new_file_on == 'lines':
            self.current_line = 0
            self.log_start = datetime.datetime.now()
        elif self.new_file_on == 'time':
            self.current_line = 0
            self.log_start = datetime.datetime.now()

        self.current_file_name = f"{self.name}_{self.log_start.isoformat()}.log"
        self.current_file_path = self.log_path / self.current_file_name
        self.current_file = open(self.current_file_path, mode='w')

    def add(self, obj):
        """
        Add an object to the trancript.
        """
        self.current_line += 1
        if self.current_line % self.lines_per_flush == 0:
            self.current_file.flush()

        if self.new_file_on == 'lines':
            if self.current_line >= self.lines_per_log:
                self.create_new_log()

        elif self.new_file_on == 'time' or self.new_file_on == 'day':
            now = datetime.datetime.now()
            dt = now - self.log_start
            if dt >= self.time_per_log:
                self.create_new_log()

        timestamp = datetime.datetime.now().isoformat()
        text = json.dumps(obj)
        text = f"{timestamp}::::{text}\n"
        self.current_file.write(text)

    def close(self):
        if self.current_file is not None:
            self.current_file.close()

    def __del__(self):
        self.close()


class TranscriptLogger(logging.Logger):
    """
    Adds log.transcript() method, which writes a message to a transcript.
    """

    def __init__(
        self, 
        name:str, 
        log_level, 
        output_stream:io.TextIOBase=sys.stderr,
        flush_every:int=0,
        use_logfile:bool=False, 
        logfile_path:typing.Union[str,pathlib.Path]=None, 
        use_transcript:bool=False, 
        transcript_path:typing.Union[str,pathlib.Path]=None, 
        transcript_name:str=None
    ) -> "TranscriptLogger":

        super().__init__(name=name)
        self.setLevel(log_level)
        self.consolehandler = logging.StreamHandler(stream=output_stream)
        self.consolehandler.setLevel(log_level)
        cf = logging.Formatter('%(levelname)s::%(message)s')
        self.consolehandler.setFormatter(cf)
        self.addHandler(self.consolehandler)
        self.propagate = False
        self.tr = None
        
        self._count = 0
        self._countLock = threading.Lock()
        self.flush_every=flush_every
        
        self.use_logfile = use_logfile

        if use_logfile:
            if logfile_path is None:
                logfile_path = 'logs/log.log'
            self.logfile_path = pathlib.Path(logfile_path)
            if not self.logfile_path.parent.exists():
                self.warning(f"Logs directory does not exist, making directory: {self.logfile_path.parent}")
                os.makedirs(self.logfile_path.parent)

            self.filehandler = logging.FileHandler(self.logfile_path)
            self.filehandler.setLevel(log_level)
            ff = logging.Formatter('%(asctime)s--%(levelname)s::%(message)s')
            self.filehandler.setFormatter(ff)
            self.addHandler(self.filehandler)

        # Configure transcript, and remember to close it!
        self.use_transcript = use_transcript
        if use_transcript:
            self.tr = Transcript(log_path=transcript_path, name=transcript_name, new_file_on='day', lines_per_log=100, time_per_log='24:00:00')

    def transcript(self, msg):
        if self.use_transcript:
            self.tr.add(msg)
        else:
            raise ValueError("Received transcript log message but no transcript is enabled.")

    # See: https://stackoverflow.com/questions/37025119/how-to-override-method-of-the-logging-module
    # for examples of overriding logging methods...
    def warning(self, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).warning(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).info(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).debug(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).critical(msg, *args, **kwargs)

    def log(self, level, msg, *args, **kwargs):
        flush=False
        self._countLock.acquire()
        self._count += 1
        self._countLock.release()

        if (self.flush_every > 0) and (self.flush_every % self._count == 0):
            self.consolehandler.flush()

        return super(TranscriptLogger, self).log(level, msg, *args, **kwargs)



# See: https://stackoverflow.com/questions/39492471/how-to-extend-the-logging-logger-class
class PipeLogger(logging.Logger):
    """
    Abstraction of inter-process communication with the logging process.
    Intended to be used as a drop-in replacement for a python logging object.
    """

    def __init__(self, log_tx, name=''):
        self.log_tx = log_tx
        self.name = name

    def log(self, level, msg):
        """
        Send a message parcel to the logging process...
        """
        if self.log_tx is None:
            raise Exception(f"Tried to send logging message to LogServer but pipe is not available")
        else:
            if self.name != '':
                msg = f'{self.name}: {msg}'
            parcel = {'level': level, 'msg': msg}
            self.log_tx.send(parcel)

    def transcript(self, msg):
        self.log('transcript', msg)

    def debug(self, msg):
        self.log(logging.DEBUG, msg)

    def info(self, msg):
        self.log(logging.INFO, msg)

    def warning(self, msg):
        self.log(logging.WARNING, msg)

    def error(self, msg):
        self.log(logging.ERROR, msg)

    def critical(self, msg):
        self.log(logging.CRITICAL, msg)



class LoggerProcess(object):
    """
    Manages / spawns a singleton process for centralized logging on a multi-process application.
    Also provides an inter-process pipe abstraction for communicating with the logging process
    """

    QUIT_PROC_SIGNAL = "quit_logger"

    def __init__(
        self, 
        logger_name='LOGPROC', 
        log_level_console:int=logging.INFO, 
        log_format_console:str='%(levelname)s::%(message)s',
        log_level_file:int=logging.INFO, 
        log_format_file:str='%(asctime)s--%(levelname)s::%(message)s',
        log_file_name:str='logs/log.log', 
        date_format:str="%Y-%m-%d %H:%M:%S",
        transcript_path:str=None, 
        transcript_name:str=None, 
        output_stream:io.TextIOBase=sys.stderr,
        flush_every:int=0  # flush output_stream every flush_every log messages, if 0 never flush explicitly
        ):

        self.recv_pipe, self.send_pipe = Pipe(duplex=False)
        self.process = Process(target=_logging_proc_main, args=(
            self.recv_pipe,
            logger_name,
            log_level_console,
            log_format_console,
            log_level_file,
            log_format_file,
            log_file_name,
            date_format,
            transcript_path,
            transcript_name,
            output_stream,
            flush_every
        ))


    def start(self):
        """
        Spawn/start the process
        """
        self.process.start()

    def join(self):
        """
        Send the QUIT_PROC_SIGNAL and wait for the process to end.
        """
        self.send_pipe.send(LoggerProcess.QUIT_PROC_SIGNAL) # Send quit message to the log_proc
        self.process.join()

    def setLevel(self, log_level:int=logging.INFO):
        """
        Set the global log level
        """
        parcel = {'level': 'setlevel', 'msg': log_level}
        self.send_pipe.send(parcel)


    def quit(self):
        """
        Convenience alias for join
        """
        self.join()

    def close(self):
        """
        Convenience alias for join
        """
        self.join()

    def get_logger(self, name: str="") -> PipeLogger:
        """
        Get an instance of LogPipe, which wraps communication with the Logging Process
        """
        return PipeLogger(self.send_pipe, name=name)


#---------------------------------------
# LOGGING PROCESS FUNCTION
def _logging_proc_main(
    pipe_rx, 
    logger_name:str, 
    log_level_console:int,
    log_format_console:str='%(levelname)s::%(message)s',
    log_level_file:int=None, 
    log_format_file:str='%(asctime)s--%(levelname)s::%(message)s',
    log_file_name:str=None, 
    date_format:str=None,
    transcript_logs_path:str=None, 
    transcript_name:str=None, 
    output_stream:io.TextIOBase=None, 
    flush_every:int=0
    ):

    # Configure Logger
    log = logging.getLogger(logger_name)
    log.setLevel(log_level_console)
    consolehandler = logging.StreamHandler(stream=output_stream)
    consolehandler.setLevel(log_level_console)
    consoleformatter = logging.Formatter(log_format_console, date_format)
    consolehandler.setFormatter(consoleformatter)
    log.addHandler(consolehandler)
    log.propagate = False

    using_logfile = False
    using_transcript = False
    transcript = None
    num_log_lines = 0

    if log_level_file is not None:
        if log_file_name is None:
            log_file_name = 'logs/log.log'
        log_file_name = pathlib.Path(log_file_name)
        if not log_file_name.parent.exists():
            log.warning(f"Logs directory does not exist, making directory: {log_file_name.parent}")
            os.makedirs(log_file_name.parent)

        filehandler = logging.FileHandler(log_file_name)
        filehandler.setLevel(log_level_file)
        fileformatter = logging.Formatter(log_format_file, date_format)
        filehandler.setFormatter(fileformatter)
        log.addHandler(filehandler)
        using_logfile = True

    # Configure transcript, and remember to close it!
    if transcript_logs_path is not None:
        transcript = Transcript(transcript_logs_path, transcript_name, new_file_on='day', lines_per_log=100, time_per_log='24:00:00')
        using_transcript = True

    # Start listening...
    log.info("Start Logging Server Process...")
    while True:
        try:
            rcvd = pipe_rx.recv() # blocks until there is something to receive...
            if rcvd == LoggerProcess.QUIT_PROC_SIGNAL:
                break;

            if rcvd['level'] == 'transcript':
                if using_transcript:
                    transcript.add(rcvd['msg'])
                else:
                    raise Exception("Received transcript write message but no transcript is enabled.")
            elif rcvd['level'] == 'setlevel':
                newlevel = int(rcvd['msg'])
                log.log(100, f"Setting logger level to {newlevel}")
                log.setLevel(newlevel)
                consolehandler.setLevel(newlevel)
            else:
                # multiprocess Pipe connections do pickling of python objects in the background...
                # so we should expect a python dict with two keys: level and msg
                log.log(rcvd['level'], rcvd['msg'])
                num_log_lines += 1
                if (flush_every > 0) and (num_log_lines % flush_every == 0):
                    #print("FLUSH!")
                    consolehandler.flush()
        except KeyboardInterrupt as e:
            # NOTE: it is the responsibility of client code to catch a KeyboardInterrupt and call .close() on the LoggerProcess
            log.warning("Received KeyboardInterrupt in Logging Process, ignoring until process.join is called by parent process.")
        except Exception as e:
            log.critical(f"Encountered exception in Logging Process: {str(e)}")
            log.critical(traceback.format_exc())

            if using_logfile:
                filehandler.close()

            consolehandler.close()

            if using_transcript:
                transcript.close()
            raise e

    print("Exiting Logging Server Process", flush=True)
    if using_transcript:
        transcript.close()
    if using_logfile:
        filehandler.close()
    consolehandler.close()




class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'




import threading
import argparse

def str2bool(v):
    """
    Type function for argparse to parse boolean flags
    """
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")

def int_or_str(text):
    """Helper function for argument parsing."""
    try:
        return int(text)
    except ValueError:
        return text


class PeriodicTimer(object):
    """
    A periodic task running in threading.Timers
    """

    def __init__(self, interval, function, *args, **kwargs):
        self._lock = threading.Lock()
        self._timer = None
        self.function = function
        self.interval = interval
        self.args = args
        self.kwargs = kwargs
        self._stopped = True
        if kwargs.pop('autostart', True):
            self.start()

    def start(self, from_run=False):
        self._lock.acquire()
        if from_run or self._stopped:
            self._stopped = False
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self._lock.release()

    def _run(self):
        self.start(from_run=True)
        self.function(*self.args, **self.kwargs)

    def stop(self):
        self._lock.acquire()
        self._stopped = True
        self._timer.cancel()
        self._lock.release()


# Used to broadcast parameter lists of potentially different lengths...
# param_list is a dict in the same format as kwargs
# ex.
#   broadcast_params('repeat_last', arg1=True, arg2=[1,2,3,4], arg3=['foo', 'bar'])
#   returns:
#       {'arg1': [True, True, True, True], 'arg2': [1,2,3,4], 'arg3': ['foo', 'bar', 'bar', 'bar']}
#       4

def broadcast_params(fill_mode='repeat_last', **param_list):
    bparams = dict()
    max_len=1

    # First pass
    for key, val in param_list.items():
        if type(val) not in (list, tuple):
            val = [val]
        else:
            max_len = max(max_len, len(val))

        bparams[key] = val

    # Second pass
    for key in bparams:
        if len(bparams[key]) < max_len:
            newlist = list()
            if fill_mode == 'repeat_last':

                for val in bparams[key]:
                    newlist.append(val)

                repeat_me = newlist[-1]

                for i in range(max_len - len(newlist)):
                    newlist.append(repeat_me)
            else:
                raise Exception(f"Unknown fill_mode '{fill_mode}' in broadcast_params()")

            bparams[key] = newlist


    return bparams, max_len
