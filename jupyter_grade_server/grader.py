"""
Implementation of a grader compatible with XServer
"""
import html
import imp
import sys
import time
import json
from path import Path
import logging
import multiprocessing
from statsd import statsd
from urllib.request import urlretrieve
import urllib.error
import tempfile
import operator
import string
import os
import json

from . import nbgrader


def format_errors(errors):
    esc = html.escape
    error_string = ''
    error_list = [esc(e) for e in errors or []]
    if error_list:
        items = '\n'.join([f'<li><pre>{e}</pre></li>\n' for e in error_list])
        error_string = f'<ul>\n{items}</ul>\n'
        error_string = f'<div class="result-errors">{error_string}</div>'
    return error_string


def to_dict(result):
    # long description may or may not be provided.  If not, don't display it.
    # TODO: replace with mako template
    esc = html.escape
    if result[1]:
        long_desc = '<p>{}</p>'.format(esc(result[1]))
    else:
        long_desc = ''
    return {'short-description': esc(result[0]),
            'long-description': long_desc,
            'correct': result[2],   # Boolean; don't escape.
            'expected-output': esc(result[3]),
            'actual-output': esc(result[4])
            }


class Grader:
    results_template = """
<div class="test">
<h3>Notebook output and hidden test results:</h3>
  <section>
    <div class="shortform">
      <br>
      {status}
    </div>
    <div class="longform">
      {errors}
      {results}
      <br>
    </div>
  </section>
</div>
"""

    results_error_template = """
<div class="test">
<h3>Error during grading:</h3>
  <section>
    <div class="shortform">
      <br>
      {errors}
    </div>
    <div class="longform">
      {results}
      <br>
    </div>
  </section>
</div>
"""

    debugging_tips = '''
<h4>Tips</h4>
<ul>
<li>Before you submit, make sure everything runs as expected.  From the Jupyter menu bar select <b>Kernel > Restart &amp; Run All</b>.</li>
<li>Remember to save the notebook before uploading the file.</li>
<li>Check that your installed version of each Python package is the correct version.  Run <pre>!pip show package_name
!pip install package_name==1.2.3</pre></li>
<li>If many tests in a row fail, an error while executing the solution right before may prevent all these tests from completing.  Check for typos or mistakes in the solution.</li>
</ul>
'''

    def __init__(self, grader_root='/tmp/', fork_per_item=True, logger_name=__name__, **kwargs):
        """
        grader_root = root path to graders
        fork_per_item = fork a process for every request
        logger_name = name of logger
        """
        self.log = logging.getLogger(logger_name)
        self.grader_root = Path(grader_root)

        self.fork_per_item = fork_per_item

        self.start_dir = Path(os.getcwd())

    def __call__(self, content):
        if self.fork_per_item:
            q = multiprocessing.Queue()
            proc = multiprocessing.Process(target=self.process_item, args=(content, q))
            proc.start()
            proc.join()
            try:
                reply = q.get_nowait()
            except Exception as e:
                results = self._grade_failed_result(903,
                        f'queue wait error',
                        e=e)
                return {
                    'correct': results['points'] >= results['possible'],
                    'score': results['score'],
                    'msg': self.render_results(results),
                }
            if isinstance(reply, Exception):
                #raise reply
                results = self._grade_failed_result(914,
                        f'uncaught error occurred',
                        e=e)
                return {
                    'correct': results['points'] >= results['possible'],
                    'score': results['score'],
                    'msg': self.render_results(results),
                }
            else:
                return reply
        else:
            return self.process_item(content)

    def _grade_failed_result(self, error_code, priv_msg='', pub_msg='Internal grader error', contact=True, e=None):
        self.log.warning(f'GRADER ERROR {error_code}: {priv_msg} ({repr(e)})')
        if contact:
            msg = (f'Please contact the course administrators to fix the problem, '
                   f'along with the following information: <pre>{pub_msg} '
                   f'({time.ctime()}, error code {error_code})</pre>')
        else:
            msg = pub_msg
        return {
            'grader-failed': True,
            'grader-error-msg': msg,
            'points': 0,
            'possible': 100,
            'score': 0,
            'feedback-html': '',
        }

    def _grade(self, grader_config, files, tmpdir):
        tmpdir = Path(tmpdir)
        self.log.info('GRADING START')

        # Parse input config
        try:
            prob_name = str(grader_config['name'])
            # Sanitize for the file system
            allowed = string.digits + string.ascii_letters + '-_ '
            prob_name = ''.join(filter(allowed.__contains__, prob_name))

            file_url = str(files[prob_name+'.ipynb'])
            # Sanitize to ensure only a public URL
            if not file_url.startswith('https://'):
                return self._grade_failed_result(312,
                        'invalid submitted file download URL ({file_url})',
                        e=e)
        except KeyError as e:
            return self._grade_failed_result(323,
                    'incorrect grader content from the XQueue ({grader_config}, {files})',
                    e=e)

        # Init file structure in the temp dir
        self._prepare_tmpdir(tmpdir, prob_name)
        download_path = tmpdir / 'submitted' / 'student' / prob_name / prob_name+'.ipynb'

        # Download student submission notebook to the temp dir
        try:
            exc = AssertionError('this error cannot be thrown')
            for i in range(3):  # Three tries in case of network interruption
                if i > 0:
                    time.sleep(5)  # Wait before retrying
                try:
                    student_file, headers = urlretrieve(file_url, download_path)
                    exc = None
                    break
                except urllib.error.URLError as e:
                    exc = e
                    self.log.warning(f'Submitted file download error (retrying): {repr(e)}')
            if exc is not None:
                raise exc
        except OSError as e:  # OSError is a parent class of all urllib errors
            return self._grade_failed_result(950,
                    f'cannot download submitted file from the XQueue ({file_url})',
                    e=e)
        try:
            with open(download_path, 'r') as f:
                json.load(f)  # Test if able to read and parse as JSON
        except UnicodeDecodeError as e:
            return self._grade_failed_result(669,
                    f'cannot parse JSON of submitted file ({file_url})',
                    'An error occurred during grading.  You may have submitted the wrong file or the file is corrupted.',
                    contact=False,
                    e=e)
        except json.JSONDecodeError as e:
            return self._grade_failed_result(788,
                    f'cannot parse JSON of submitted file ({file_url}, {open(download_path).read(50)!r})',
                    'An error occurred during grading.  You may have submitted the wrong file or the file is corrupted.',
                    contact=False,
                    e=e)
        except (OSError, Exception) as e:
            return self._grade_failed_result(370,
                    f'cannot read submitted file from disk ({file_url})',
                    e=e)

        # Call out to nbgrader to do the grading
        tmpdir.chdir()
        try:
            nbgrader.autograde(prob_name)
            feedback_html = nbgrader.get_feedback(prob_name)
            points, max_points = nbgrader.get_grade(prob_name)
            if int(points) == points:
                points = int(points)
            if int(max_points) == max_points:
                max_points = int(max_points)
        except BaseException as e:
            return self._grade_failed_result(383,
                    'error during nbgrader auto-grading, feedback generation, or grade output',
                    'An error occurred during grading.  You may have submitted the wrong file or your code may have taken too long to run or used too much memory.',
                    contact=False,
                    e=e)
        finally:
            self.start_dir.chdir()

        # For debugging
        #import subprocess
        #subprocess.call('bash')

        tips = ''
        if points < max_points:
            tips = self.debugging_tips

        # Return results
        self.log.info('GRADING SUCCESS')
        return {
            'grader-failed': False,
            'grader-error-msg': '',
            'points': points,
            'possible': max_points,
            'score': points/max_points,
            'feedback-html': f'{feedback_html}{tips}',
        }

    def _prepare_tmpdir(self, tmpdir, prob_name):
        # Make location for the submitted file
        (tmpdir / 'submitted').mkdir()
        (tmpdir / 'submitted' / 'student').mkdir()
        (tmpdir / 'submitted' / 'student' / prob_name).mkdir()
        # Copy template database
        relocate = self.start_dir / 'relocate'
        (relocate / 'gradebook.db').copy(tmpdir / 'gradebook.db')
        # Symlink grader files
        (relocate / 'nbgrader_config.py').symlink(tmpdir / 'nbgrader_config.py')
        (relocate / 'source').symlink(tmpdir / 'source')
        (relocate / 'release').symlink(tmpdir / 'release')

    def grade(self, grader_config, files):
        with tempfile.TemporaryDirectory(prefix='notebook-grader-') as tmpdir:
            return self._grade(grader_config, files, tmpdir)

    def process_item(self, content, queue=None):
        try:
            statsd.increment('xqueuewatcher.process-item')
            body = content['xqueue_body']
            files = content['xqueue_files']

            # Delivery from the lms
            body = json.loads(body)
            files = json.loads(files)
            #student_response = body['student_response']
            payload = body['grader_payload']
            try:
                grader_config = json.loads(payload)
            except ValueError as err:
                # If parsing json fails, erroring is fine--something is wrong in the content.
                # However, for debugging, still want to see what the problem is
                statsd.increment('xqueuewatcher.grader_payload_error')

                self.log.debug(f"error parsing: '{payload}' -- {err}")
                raise

            #self.log.debug(f"Processing submission, grader payload: {payload}")
            #relative_grader_path = grader_config['grader']
            #grader_path = (self.grader_root / relative_grader_path).abspath()
            start = time.time()
            results = self.grade(grader_config, files)

            statsd.histogram('xqueuewatcher.grading-time', time.time() - start)

            # Make valid JSON message
            reply = {
                'correct': results['points'] >= results['possible'],
                'score': results['score'],
                'msg': self.render_results(results),
            }

            statsd.increment('xqueuewatcher.replies (non-exception)')
        except Exception as e:
            self.log.exception("process_item")
            if queue:
                queue.put(e)
            else:
                raise
        else:
            if queue:
                queue.put(reply)
            return reply

    def render_results(self, results):
        if results['grader-failed']:
            status = 'GRADING ERROR'
            template = self.results_error_template
        else:
            template = self.results_template
            if results['points'] >= results['possible']:
                label = 'Correct'
            elif results['points'] > 0:
                label = 'Partially correct'
            else:
                label = 'Incorrect'
            status = ('<b>{label}<br />Total score: {score:.0%} ({points}/{possible})</b>'
                      .format(label=label, **results))
        return template.format(status=status,
                               errors=results['grader-error-msg'] or '',
                               results=results['feedback-html'] or '')
