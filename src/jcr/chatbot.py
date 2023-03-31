# State-aware Chatbot Utilities
#
# Chatbot Utilities with State-awareness and Input capture callbacks.
#
# Copyright (C) 2022- J. Chaim Reus
#
# This is based on Natural Language Toolkit: Chatbot Utilities
# NLTK Project, Authors: Steven Bird <stevenbird1@gmail.com>
# Based on an Eliza implementation by Joe Strout <joe@strout.net>,
# Jeff Epler <jepler@inetnebr.com> and Jez Higgins <jez@jezuk.co.uk>.

import random
import re

default_reflections = {
    "i am": "you are",
    "i was": "you were",
    "i": "you",
    "i'm": "you are",
    "i'd": "you would",
    "i've": "you have",
    "i'll": "you will",
    "my": "your",
    "you are": "I am",
    "are you": "am I",
    "you were": "I was",
    "you've": "I have",
    "you'll": "I will",
    "your": "my",
    "yours": "mine",
    "you": "I",
    "me": "you",
}

demo_pairs = {
    'default': [
    ['My name is (.*)',['Hi %1']],
    ["(hey|hello|yo|hi|hola|what's good?)",
        ["Hello, would you like to share a story?<<<story>>>",'Nice to meet you!',"Hope you're doing good","Hi there! Would you like to ask anything?<<<questions>>>"]],
    [".*(question|questions|ask|asking).*",
        ["I can answer some questions, what would you like to know?<<<questions>>>", "Do you want to ask me a question?<<<questions>>>"]],
    [".*(story|submit|add|contribute|contribution|voice|person).*",
        ["Do you have a story to share?<<<story>>>", "Do you want to contribute something?<<<story>>>"]],

    ["(bye|see you later|goodbye|nice chatting with you)",
        ["Goodbye","Thank you for your contribution","be well"]],
    ["(thanks|thank you|that's helpful|awesome,thanks|thanks for helping me)",
        ["happy to help!","anytime","no problem"]],
    ['(.*)?',
        ['Hmm... %1']],
    ],

    'story': [
        ["(yes|yeah|ja|ya|y|sure|ok)",
            ["What do you remember from when you were a child?@@@capture@@@", "What do you think of ancestor worship?", "Could you name one, or a few, people, who you consider to be good ancestors today?@@@capture@@@"]],
        ["(done|no|i'm done|that's all)",
            ["Ok, let me know if you'd like to share more.<<<default>>>"]],
        ["(.*)?",
            ["Is there anything else you'd like to share?", "Would you like to share another story?"]],
    ],
    'questions': [
        ["(yes|yeah|ja|ya|y|sure|ok)",
            ["I can give you a reference?", "I can tell you what some previous people have said."]],
        [".*(reference|know|information).*",
            ["Here is a reference", "Here is one of many references."]],
        [".*(people|previous).*",
            ["Somebody said this", "And somebody said this."]],
        [".*(done|no|i'm done|that's all).*",
            ["Ok, let me know if you'd like to share more.<<<default>>>"]],
        ["(.*)?",
            ["Is there anything else you'd like to ask?"]]
    ]
}


class StatefulChat:
    _re_command = re.compile(r'@@@(capture)@@@', re.IGNORECASE)
    _re_state = re.compile(r'<<<([A-Za-z0-9_]+)>>>', re.IGNORECASE)

    def __init__(self, pairs=[], reflections=None, capture_callback=None, state_change_callback=None, name='statebot'):
        """
        Initialize the chatbot.  Pairs is a dictionary of states, each associated with a list of patterns and responses.
        Each pattern is a regular expression matching the user's statement or question,
        e.g. r'I like (.*)'.
        For each such pattern a list of possible responses is given, e.g. ['Why do you like %1', 'Did you ever dislike %1'].
        Material which is matched by parenthesized sections of the patterns (e.g. .*) is mapped to
        the numbered positions in the responses, e.g. %1.

        :type pairs:    dict or list of tuple
                        dictionary of <state_name>:<list of tuples> ... or <list of tuples>
                        If pairs is provided without state information (e.g. as a list of lists)
                        then all pairs fall into the default state 'default'
        :param pairs: The patterns and responses
        :type reflections: dict
        :param reflections: A mapping between first and second person expressions
        :rtype: None
        """
        if type(pairs) is list:
            pairs = {'default': pairs}

        self._capture_callback = capture_callback
        self._state_change_callback = state_change_callback
        self._pairs = dict()
        for state in pairs:
            newpairs = list()
            for (input_pattern, resps) in pairs[state]:
                newresps = list()
                for res in resps:
                    newres = {'response': res, 'command': None, 'state_change': None}
                    # Does reply contain a @@@capture@@@ keyword?
                    match = self._re_command.search(newres['response'])
                    if match is not None:
                        newres['response'] = newres['response'].replace(match.group(0), '')
                        newres['command'] = match.group(1)

                    # Does reply contain a <<<state>>> keyword?
                    match = self._re_state.search(newres['response'])
                    if match is not None:
                        newres['response'] = newres['response'].replace(match.group(0), '')
                        newres['state_change'] = match.group(1)

                    newresps.append(newres)
                newpairs.append((re.compile(input_pattern, re.IGNORECASE), newresps))
            self._pairs[state] = newpairs

        if reflections is None:
            reflections = default_reflections

        self._reflections = reflections
        self._regex = self._compile_reflections()
        self.init_conversation('default', name)

    def init_conversation(self, state='default', name=None):
        self._state = state
        if name is not None:
            self.name = name
        self._capture_next = False

    def _compile_reflections(self):
        sorted_refl = sorted(self._reflections, key=len, reverse=True)
        return re.compile(
            r"\b({})\b".format("|".join(map(re.escape, sorted_refl))), re.IGNORECASE
        )

    def __copy__(self):
        """
        Useful for making multiple independent chat sessions without recompiling
        all the pairs & regexes... these data structures are shared between copies.
        """
        copy = StatefulChat({}, [])
        copy._capture_callback = self._capture_callback
        copy._state_change_callback = self._state_change_callback
        copy._capture_next = self._capture_next
        copy._state = self._state
        copy._pairs = self._pairs
        copy._reflections = self._reflections
        copy._regex = self._regex
        return copy

    def _substitute(self, str):
        """
        Substitute words in the string, according to the specified reflections,
        e.g. "I'm" -> "you are"

        :type str: str
        :param str: The string to be mapped
        :rtype: str
        """

        return self._regex.sub(
            lambda mo: self._reflections[mo.string[mo.start() : mo.end()]], str.lower()
        )

    def _wildcards(self, response, match):
        pos = response.find("%")
        while pos >= 0:
            num = int(response[pos + 1 : pos + 2])
            response = (
                response[:pos]
                + self._substitute(match.group(num))
                + response[pos + 2 :]
            )
            pos = response.find("%")
        return response


    def _get_response(self, str):
        """
        Generate a response to the user input given the current state.

        :type str: str
        :param str: The string to be mapped
        :rtype: <str>: the response, <str|None>: associated state change, <str|None>: associated command
        """

        # check each pattern
        print(f"Matching >>{str}<<")
        pairs = self._pairs[self._state]
        resp = ''
        state_change = None
        command = None
        for (pattern, response) in pairs:
            match = pattern.match(str)

            # did the pattern match?
            if match:
                resp = random.choice(response)  # pick a random response

                command = resp['command']
                state_change = resp['state_change']
                resp = resp['response']

                resp = self._wildcards(resp, match)  # process wildcards

                # fix munged punctuation at the end
                if resp[-2:] == "?.":
                    resp = resp[:-2] + "."
                if resp[-2:] == "??":
                    resp = resp[:-2] + "?"

                return resp, state_change, command

        return resp, state_change, command

    def respond(self, input_text):
        """
        Get response for a given input text, runs any necessary callbacks and runs state changes.
        """
        if self._capture_next:
            if self._capture_callback is not None:
                self._capture_callback(input_text)
            self._capture_next = False

        text = input_text
        while text[-1] in "!.":
            text = text[:-1]

        resp, state_change, command = self._get_response(text)

        if state_change is not None:
            if self._state_change_callback is not None:
                self._state_change_callback(input_text, self._state, state_change)
            self._state = state_change

        if command is not None:
            if command == 'capture':
                self._capture_next = True

        return resp


    # Hold a conversation with a chatbot
    def converse(self, quit_signal="quit"):
        self.init_conversation()
        user_input = ""
        while user_input != quit_signal:
            user_input = quit_signal
            try:
                user_input = input(">")
            except EOFError:
                print(user_input)
            if user_input:
                print(self.respond(user_input))


if __name__ == '__main__':

    def capfunc(str):
        print(f"CAPTURE: {str}")

    def statefunc(str, oldstate, newstate):
        print(f"STATE CHANGE: {oldstate}->{newstate}")

    bot = StatefulChat(demo_pairs, reflections=default_reflections, capture_callback=capfunc, state_change_callback=statefunc)

    user_input = ""
    quit_signal = "quit"
    while user_input != quit_signal:
        user_input = quit_signal
        try:
            user_input = input(">")
        except EOFError:
            print(user_input)

        if user_input:
            while user_input[-1] in "!.":
                user_input = user_input[:-1]
            resp = bot.respond(user_input)
            print(resp)
