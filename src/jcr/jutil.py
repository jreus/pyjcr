import os, traceback
import argparse
import smtplib
import ssl
import json
from pathlib import Path
from datetime import timedelta, datetime, date
from email.message import EmailMessage
import logging
from multiprocessing import Process, Pipe

class Emailer(object):
    """
    A class for sending an occasional email for debugging & notification purposes.
    Note: This class logs into the SMTP server each time it sends a message.
        Don't use it for sending lots of emails at a time.
    """

    def __init__(self, server, port, username, password, from_email, subject_prefix='', enabled=True):
        self.smtp_server = server
        self.port = int(port)
        self.username = username
        self.password = password
        self.from_email = from_email
        self.subject_prefix = subject_prefix
        self.enabled = enabled
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
                    raise Exception("No security set for Emailer")

            except smtplib.SMTPServerDisconnected as ex:
                print(f"::EMAIL ERROR:: Tried to send email, but could not log in to SMTP server: {ex}")
                result = ex
            except smtplib.SMTPDataError as ex:
                print(f"::EMAIL ERROR:: Tried to send email, but received data error: {ex}")
                result = ex
        else:
            result = "WARNING: Tried to send Email message, but emailer.enabled == False!"
            print(result)

        return result



class Transcript(object):
    """
    A class for managing writing JSON objects into timestamped transcripts.

    NOTE: Additions to the transcript are not flushed into the file buffer until
        1. lines_per_flush is exceeded
        2. a new logfile is created
        3. the Transcript is closed
    """

    def __init__(self, log_path, name='tr', new_file_on='time', lines_per_log=1000, time_per_log='01:00:00', lines_per_flush=100):
        if new_file_on == 'day':
            # New file at midnight
            self.time_per_log = timedelta(hours=24)

        elif new_file_on == 'lines':
            # New file every lines_per_log
            self.lines_per_log = lines_per_log

        elif new_file_on == 'time':
            # New file every time_per_log HH:MM:SS
            tsegs = time_per_log.split(':')
            self.time_per_log = timedelta(
                hours=int(tsegs[0]),
                minutes=int(tsegs[1]),
                seconds=int(tsegs[2])
            )

        else:
            raise Error(f"Unknown new_file_on value '{new_file_on}'")

        self.current_file = None
        self.current_line = 0
        self.lines_per_flush = lines_per_flush
        self.log_path = Path(os.path.abspath(log_path))
        if not self.log_path.exists():
            os.makedirs(self.log_path)

        self.name = name
        self.new_file_on = new_file_on
        self.create_new_log()



    def create_new_log(self):

        if self.current_file is not None:
            self.current_file.close()

        if self.new_file_on == 'day':
            self.current_line = 0
            self.log_start = datetime.combine(date.today(), datetime.min.time())
        elif self.new_file_on == 'lines':
            self.current_line = 0
            self.log_start = datetime.now()
        elif self.new_file_on == 'time':
            self.current_line = 0
            self.log_start = datetime.now()

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
            now = datetime.now()
            dt = now - self.log_start
            if dt >= self.time_per_log:
                self.create_new_log()

        timestamp = datetime.now().isoformat()
        text = json.dumps(obj)
        text = f"{timestamp}::::{text}\n"
        self.current_file.write(text)


    def close(self):
        self.current_file.close()



class LoggerProcess(object):
    """
    Manages / spawns a singleton process for centralized logging on a multi-process application.
    Also provides an inter-process pipe abstraction for communicating with the logging process
    """

    QUIT_PROC_SIGNAL = "quit_logger"

    def __init__(self, logger_name='LOGPROC', log_level_console=logging.INFO, log_level_file=logging.INFO, log_file_name='logs/log.log', transcript_path=None, transcript_name=None):

        self.recv_pipe, self.send_pipe = Pipe(duplex=False)
        self.process = Process(target=_logging_proc_main, args=(
            self.recv_pipe,
            logger_name,
            log_level_console,
            log_level_file,
            log_file_name,
            transcript_path,
            transcript_name
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


    def close(self):
        """
        Convenience alias for join
        """
        self.join()

    def get_logger(self, name=""):
        """
        Get an instance of LogPipe, which wraps communication with the Logging Process
        """
        return PipeLogger(self.send_pipe, name=name)


#---------------------------------------
# LOGGING PROCESS FUNCTION
def _logging_proc_main(pipe_rx, logger_name, log_level_console, log_level_file=None, log_file_name=None, transcript_logs_path=None, transcript_name=None):

    # Configure Logger
    log = logging.getLogger(logger_name)
    log.setLevel(log_level_console)
    ch = logging.StreamHandler()
    ch.setLevel(log_level_console)
    cf = logging.Formatter('%(levelname)s::%(message)s')
    ch.setFormatter(cf)
    log.addHandler(ch)
    log.propagate = False

    using_logfile = False
    using_transcript = False
    transcript = None

    if log_level_file is not None:
        if log_file_name is None:
            log_file_name = 'logs/log.log'
        log_file_name = Path(log_file_name)
        if not log_file_name.parent.exists():
            log.warning(f"Logs directory does not exist, making directory: {log_file_name.parent}")
            os.makedirs(log_file_name.parent)

        fh = logging.FileHandler(log_file_name)
        fh.setLevel(log_level_file)
        ff = logging.Formatter('%(asctime)s--%(levelname)s::%(message)s')
        fh.setFormatter(ff)
        log.addHandler(fh)
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
            else:
                # multiprocess Pipe connections do pickling of python objects in the background...
                # so we should expect a python dict with two keys: level and msg
                log.log(rcvd['level'], rcvd['msg'])
        except KeyboardInterrupt as e:
            log.warning("Received KeyboardInterrupt in Logging Process, ignoring until process.join is called by parent process.")
        except Exception as e:
            log.critical(f"Encountered exception in Logging Process: {str(e)}")
            log.critical(traceback.format_exc())
            if using_transcript:
                transcript.close()
            raise e

    if using_transcript:
        transcript.close()

    log.error("Exiting Logging Server Process")



class PipeLogger(object):
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
            raise Error(f"Tried to send logging message to LogServer but pipe is not available")
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




# Used in argparse
def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")


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
