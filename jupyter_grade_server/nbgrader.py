import base64
import re
from path import Path

import nbformat
import ansi2html

from nbgrader.apps.autogradeapp import AutogradeApp
from nbgrader.apps.generatefeedbackapp import GenerateFeedbackApp
from nbgrader.api import Gradebook, InvalidEntry


def autograde(lab_name):
    grader = AutogradeApp()
    grader.init_syspath = lambda:None
    grader.initialize([lab_name])
    grader.start()

#def _html_page_to_iframe(page):
#    STRIP_CHARS = ('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11'
#                   '\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f')
#    search = re.compile('|'.join(STRIP_CHARS))
#    data_safe = search.sub('', page)
#    b64 = base64.b64encode(data_safe.encode())
#    page_data_url = 'data:text/html;base64,' + b64.decode(encoding='ascii')
#    return f'''<iframe height="1000" width="100%" src={page_data_url}></iframe>'''
#
#def get_feedback(lab_name):
#    gen = GenerateFeedbackApp()
#    gen.init_syspath = lambda:None
#    gen.initialize([lab_name])
#    gen.start()
#    page = (Path() / 'feedback' / 'student' / lab_name / f'{lab_name}.html').read_text()
#    return _html_page_to_iframe(page)

def get_feedback(lab_name):
    nb = nbformat.read(Path() / 'autograded' / 'student' / lab_name / f'{lab_name}.ipynb', as_version=4)
    release_nb = nbformat.read(Path() / 'release' / lab_name / f'{lab_name}.ipynb', as_version=4)

    color_converter=ansi2html.Ansi2HTMLConverter(inline=True)

    def formatted_error_output(cell, whole_traceback=True):
        out_html = ''
        for output in reversed(cell.get('outputs', [])):
            if output.get('output_type') == 'error':
                if whole_traceback:
                    out_str = '\n'.join(output.get('traceback', ['Unknown error']))
                else:
                    out_str = output.get('traceback', ['Unknown error'])[-1]
                colored = color_converter.convert(out_str, full=False)
                out_html = f'''<pre>{colored}</pre>'''
                break
        return f'''
        {out_html}
        '''

    def formatted_test_output(cell, whole_traceback=False):
        max_points = cell['metadata']['nbgrader'].get('points', 0)
        points = 0
        pnumber = cell['metadata']['nbgrader'].get('grade_id', ''
                    ).replace('-test', '').replace('test', '').replace('-', '.')

        out_html = '''<pre><span style="font-weight: bold">Not Graded</span></pre>'''
        for output in reversed(cell['outputs']):
            if output.get('output_type') == 'error':
                if whole_traceback:
                    out_str = '\n'.join(output.get('traceback', ['Unknown error']))
                else:
                    out_str = output.get('traceback', ['Unknown error'])[-1]
                colored = color_converter.convert(out_str, full=False)
                out_html = f'''<pre>{colored}</pre>'''
                break
        else:
            # No error output
            if (not cell['metadata']['nbgrader'].get('solution')
                and not cell['metadata']['nbgrader'].get('task')):
                points = max_points
            out_html = '''<pre><span style="font-weight: bold; color: #00aa00">Correct</span></pre>'''

        return f'''
        <h4>Test {pnumber} (score: {points}/{max_points})</h4>
        {out_html}
        <hr>
        '''

    # Find the correct set of tests from the original release document
    test_id_map = {}
    missing_msg = '''
<h4>Test {} (MISSING!)</h4>
<pre style="color: #aa0000">
You probably deleted the cell containing this test.
To fix this, download a fresh copy of the notebook file
and copy your solutions into the fresh notebook.
</pre>
<hr>
'''
    for cell in release_nb['cells']:
        if cell.get('metadata', {}).get('nbgrader', {}).get('grade', False):
            test_id = cell['metadata']['nbgrader'].get('grade_id')
            if test_id:
                pnumber = cell['metadata']['nbgrader'].get('grade_id', ''
                            ).replace('-test', '').replace('test', '').replace('-', '.')
                test_id_map[test_id] = missing_msg.format(pnumber)

    others_out = []
    pre_output = ''
    for cell in nb['cells']:
        if cell.get('metadata', {}).get('nbgrader', {}).get('grade', False):
            test_id = cell['metadata']['nbgrader'].get('grade_id', 'unknown')
            test_out = pre_output + formatted_test_output(cell)
            pre_output = ''
            if test_id in test_id_map:
                test_id_map[test_id] = test_out
            else:
                others_out.append(test_out)
        else:
            pre_output += formatted_error_output(cell)
    # Ignoring trailing pre_output value

    all_html = (
        ''.join(test_id_map.values())
        #+ ''.join(others_out)  # Ignore tests that aren't supposed to be here
    )
    return all_html

def get_grade(lab_name):
    '''Returns the code score, excluding any manually graded problems.

    Returns a tuple (code_score, max_code_score)
    '''
    with Gradebook('sqlite:///gradebook.db') as gb:
        asgn = gb.find_submission(lab_name, 'student')
        return asgn.code_score, asgn.max_code_score
