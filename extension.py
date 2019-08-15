import sublime
import sublime_plugin

import urllib
import json
import threading
import functools
import re
import uuid
import hashlib

from aiXcoder.typescript import TypeScriptLangUtil
from aiXcoder.javascript import JavaScriptLangUtil
from aiXcoder.java import JavaLangUtil
from aiXcoder.php import PhpLangUtil
from aiXcoder.python import PythonLangUtil
from aiXcoder.cpp import CppLangUtil
from aiXcoder.codestore import CodeStore


def get_lang_util(syntax):
    if 'JavaScript' in syntax:
        return JavaScriptLangUtil()
    elif 'TypeScript' in syntax:
        return TypeScriptLangUtil()
    elif 'Java' in syntax:
        return JavaLangUtil()
    elif 'Php' in syntax:
        return PhpLangUtil()
    elif 'Python' in syntax:
        return PythonLangUtil()
    elif 'C++' in syntax:
        return CppLangUtil()
    else:
        return None


def get_ext(syntax):
    if 'JavaScript' in syntax:
        return "javascript(Javascript)"
    elif 'TypeScript' in syntax:
        return "typescript(Typescript)"
    elif 'Java' in syntax:
        return "java(Java)"
    elif 'Php' in syntax:
        return "php(Php)"
    elif 'Python' in syntax:
        return "python(Python)"
    elif 'C++' in syntax:
        return "cpp(Cpp)"
    else:
        return None


def get_uuid():
    s = sublime.load_settings("Preferences.sublime-settings")
    if s.get("aixcoder.uuid", None) is None:
        s.set("aixcoder.uuid", "sublime-" + str(uuid.uuid4()))
        sublime.save_settings("Preferences.sublime-settings")
    return s.get("aixcoder.uuid", None)


def md5Hash(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


endpoint = "https://api.aixcoder.com/predict"


def on_nav(view, href):
    # p = view.selection[0].a
    print(href)
    view.run_command("insert", {"characters": href[5:]})
    view.hide_popup()


def on_hide(view):
    popup_open = False
    view.settings().set('aiXcoder.internal_list_shown', False)


popup_open = False
r = None
results = []
long_results = []
r_map = []
last_text = ""
current_selected = 0
current_filter = ""


def render_up_down(index):
    if index < current_selected:
        return "↑"
    elif index > current_selected:
        return "↓"
    else:
        return "enter"


def render_item_long(_, r):
    style = ""
    if r == current_selected:
        style += "background-color:grey;"
    return "<div style='"+style+"'><a href='long:" + \
        _[1]+"'>"+_[0]+"</a><i style='padding-left:10px'>Shift+" + \
        render_up_down(r) + "</i></div>"


def render_item_short(_, r):
    style = ""
    if r == current_selected:
        style += "background-color:grey;"
    return "<div style='"+style+"'><a href='sort:"+_[1][len(current_filter):]+"'>" + _[
        1] + "</a><i style='padding-left:10px'>Shift+" + render_up_down(r) + "</i></div>"


def render_to_html(lang_util, r, filter_text="", selected=0, move_only=False):
    print(">>>render_html")
    print(r)
    print("filter_text=" + repr(filter_text))
    print("<<<render_html")
    global r_map, current_filter, current_selected, results, long_results
    if not move_only and (r is None or len(r) == 0):
        return ""
    if not move_only:
        results = []
        long_results = []
        r_map = []
        if filter_text != "-":
            current_filter = filter_text
        elif 'current' in r[0]:
            current_filter = r[0]['current']
        else:
            current_filter = ""
        for single_r in r:
            print("single_r =" + repr(single_r))
            if len(single_r['tokens']) > 0:
                display = lang_util.render(single_r['tokens'], 0)
                if 'r_completion' in single_r:
                    r_completion = lang_util.render(
                        single_r['r_completion'], 0)
                else:
                    r_completion = ''
                print("long display" + display)
                if len(current_filter) == 0 or (single_r['current'] + display).replace(" ", "").startswith(current_filter):
                    actual_display = single_r['current'] + display
                    if len(r_completion) > 0:
                        actual_display += r_completion
                    long_results.append((actual_display, display))
                    r_map.append(
                        ((single_r['current'] + display)[len(current_filter):], r_completion))
            if 'sort' in single_r:
                for single_sort in single_r['sort']:
                    single_sort_prob, single_sort_word = single_sort[:2]
                    if len(current_filter) == 0 or single_sort_word.startswith(current_filter):
                        results.append(
                            (single_sort_word + '\taixcoder' + str(single_sort_prob), single_sort_word))
                        r_map.append(
                            (single_sort_word[len(current_filter):], ''))
    lis = ""
    r = 0
    if selected < 0:
        selected = 0
    if selected >= len(long_results) + len(results):
        selected = len(long_results) + len(results) - 1
    current_selected = selected
    print("$$$$")
    print(long_results)
    print(results)
    for _ in long_results:
        lis += render_item_long(_, r)
        r += 1
    for _ in results:
        lis += render_item_short(_, r)
        r += 1
    if len(lis) > 0:
        return "<html><body>" + lis + "</body></html>"
    else:
        return ""


def show(html, view):
    global popup_open
    if len(html) > 0:
        view.settings().set('aiXcoder.internal_list_shown', True)
        if popup_open:
            view.update_popup(html)
        else:
            view.show_popup(html, sublime.COOPERATE_WITH_AUTO_COMPLETE, -1, 1000,
                            1000, functools.partial(on_nav, view), functools.partial(on_hide, view))
        popup_open = True
    else:
        view.settings().set('aiXcoder.internal_list_shown', False)
        popup_open = False
        view.hide_popup()


class AiXPredictThread(threading.Thread):
    def __init__(self, lang_util, view, values, headers, *args, **kwargs):
        self.lang_util = lang_util
        self.view = view
        self.values = values
        self.headers = headers
        super().__init__(*args, **kwargs)

    def run(self, retry=True):
        print("send request...")
        view = self.view
        values = self.values
        headers = self.headers
        data = urllib.parse.urlencode(values).encode("utf-8")
        req = urllib.request.Request(endpoint, data, headers)
        global r
        with urllib.request.urlopen(req) as response:
            r = response.read()
            r = r.decode('utf-8')
        projName = values['project']
        fileID = values['fileid']
        print("r=" + repr(r))
        if retry and r == 'Conflict':
            CodeStore.getInstance().invalidateFile(projName, fileID)
            return self.run(retry=False)
        else:
            maskedText = values['text']
            CodeStore.getInstance().saveLastSent(projName, fileID, maskedText)
            r = json.loads(r)
            print(r)
            html = render_to_html(self.lang_util, r, filter_text="-")
            show(html, view)


class AiXCoderAutocomplete(sublime_plugin.EventListener):
    def on_modified_async(self, view):
        syntax = view.settings().get("syntax")
        print("syntax=" + syntax)
        lang_util = get_lang_util(syntax)
        if lang_util is None:
            return

        print("====================================")
        global r, popup_open, last_text
        popup_open = view.is_popup_visible()
        if popup_open:
            prefix = view.substr(sublime.Region(0, view.selection[0].a))
            i = len(prefix) - 1
            while i >= 0 and prefix[i].isalpha():
                i -= 1
            current = prefix[i + 1:]
            if len(current) == 0 and last_text != prefix:
                show("", view)
            else:
                html = render_to_html(lang_util, r, current)
                print(html)
                show(html, view)
        if not popup_open:
            prefix = view.substr(sublime.Region(0, view.selection[0].a))
            line_end = view.line(view.selection[0].a).b
            remaining_text = view.substr(
                sublime.Region(view.selection[0].a, line_end))
            last_text = prefix
            ext = get_ext(syntax)
            print("ext = " + ext)
            fileID = view.file_name() or ("_untitled_" + str(view.buffer_id()))
            maskedText = prefix
            offset = CodeStore.getInstance().getDiffPosition(fileID, maskedText)
            md5 = md5Hash(maskedText)
            values = {
                "text": maskedText,
                "remaining_text": remaining_text,
                "ext": ext,
                "uuid": get_uuid(),
                "project": "_scratch",
                "fileid": fileID,
                "sort": 1,
                "offset": offset
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "uuid": get_uuid(),
                "ext": ext,
            }
            AiXPredictThread(lang_util, view, values, headers,
                             name="aix-predict-thread").start()


class AixConfirmCommand(sublime_plugin.TextCommand):

    def run(self, edit, index):
        view = self.view
        print("tabbed ! " + str(current_selected))
        print(r_map)
        view.run_command(
            "insert", {"characters": r_map[current_selected][0] + r_map[current_selected][1]})
        if len(r_map[current_selected][1]) > 0:
            view.run_command(
                "move", {"by": "characters", "forward": False, "amount": len(r_map[current_selected][1])})
        show("", view)


class AixMoveCommand(sublime_plugin.TextCommand):

    def run(self, edit, direction):
        view = self.view
        print("moved ! " + direction)
        if direction == "up":
            show(render_to_html(None, None,
                                selected=current_selected - 1, move_only=True), view)
        else:
            show(render_to_html(None, None,
                                selected=current_selected + 1, move_only=True), view)