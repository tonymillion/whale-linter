#!/usr/bin/env python3

import os
import urllib.request

from whalelinter.app import App
from whalelinter.dispatcher import Dispatcher
from whalelinter.commands.command import ShellCommand
from whalelinter.utils import Tools

# from whalelinter.commands.apt import Apt


class Token:
    def __init__(self, name, payload, line):
        self.name = name
        self.payload = payload
        self.line = line

        self.pointless_commands = App._pointless_commands


@Dispatcher.register(token="add")
class Add(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)
        self.is_present()
        self.download_from_url()

    def is_present(self):
        App._collecter.throw(2006, line=self.line)
        return True

    def download_from_url(self):
        if "http://" in self.payload[0] or "https://" in self.payload[0]:
            App._collecter.throw(3004, line=self.line)
            return True
        return False


@Dispatcher.register(token="copy")
class Copy(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)

        # Do not check path if the copy uses a previous stage
        if not any(
            arg.startswith("--from=") for arg in self.payload
        ) and not App._dockerfile.get("is_remote"):
            self.check_path()

    def check_path(self):
        if len(self.payload) > 1:
            self.payload = self.payload[:-1]

        for file_to_copy in self.payload:
            full_path = file_to_copy

            if not os.path.isabs(file_to_copy):
                directory = os.path.dirname(
                    os.path.abspath(App._args.get("DOCKERFILE"))
                )
                full_path = directory + "/" + file_to_copy

            if not os.path.exists(full_path):
                App._collecter.throw(
                    1004,
                    line=self.line,
                    keys={"file": file_to_copy, "directory": directory},
                )


@Dispatcher.register(token="expose")
class Expose(Token):
    def __init__(self, ports, line):
        Token.__init__(self, __class__, ports, line)

        for port in ports:
            if "-" in port:
                ports = ports + port.split("-")
                ports.remove(port)

        for port in ports:
            self.is_in_range(port)
            self.is_tcp_or_udp(port)

    def is_in_range(self, port):
        if "/" in port:
            port = port.split("/")[0]

        if int(port) < 1 or int(port) > 65535:
            App._collecter.throw(2005, line=self.line, keys={"port": port})
            return False
        return True

    def is_tcp_or_udp(self, port):
        if "/" in port:
            if port.split("/")[1] != "tcp" and port.split("/")[1] != "udp":
                App._collecter.throw(2009, line=self.line)
                return False
        return True


@Dispatcher.register(token="label")
class Label(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)
        self.payload = Tools.merge_odd_strings(Tools.sanitize_list(self.payload))
        self.labels = {l.split("=")[0]: l.split("=")[1] for l in self.payload}

        self.is_namespaced()
        self.uses_reserved_namespaces()
        # self.is_label_schema_compliant()

    def is_namespaced(self):
        for key in self.labels.keys():
            if key.count(".") < 2:
                App._collecter.throw(3005, line=self.line, keys={"label": key})

    def uses_reserved_namespaces(self):
        for key in self.labels.keys():
            for reserved_namespaces in ["com.docker", "io.docker", "org.dockerproject"]:
                if key.startswith(reserved_namespaces):
                    App._collecter.throw(
                        2014, line=self.line, keys={"label": reserved_namespaces}
                    )

    def uses_valid_characters(self):
        for key in self.labels.keys():
            if not re.match("^[a-z0-9-.]+$", key):
                App._collecter.throw(1003, line=self.line, keys={"label": key})


@Dispatcher.register(token="maintainer")
class Maintainer(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)
        App._collecter.throw(2013, line=self.line, keys={"instruction": "MAINTAINER"})


@Dispatcher.register(token="run")
class Run(Token):
    def __init__(self, payload, line):
        payload = list(filter(None, payload))

        Token.__init__(self, __class__, payload, line)
        self.is_pointless()

        shell_command = self.payload[0]
        shell_arguments = self.payload[1:]
        next_command_index = False

        if "&&" in shell_arguments:
            next_command_index = shell_arguments.index("&&")
            next_command = shell_arguments[(next_command_index + 1) :]
            shell_arguments = shell_arguments[:next_command_index]

        if shell_command in Dispatcher._callbacks["RUN"]:
            if Dispatcher._callbacks["RUN"][shell_command]["self"] is not None:
                Dispatcher._callbacks["RUN"][shell_command]["self"](
                    token="RUN",
                    command=shell_command,
                    args=shell_arguments,
                    lineno=line,
                )

        if next_command_index and next_command:
            self.__init__(next_command, self.line)

        return

    def is_pointless(self):
        if self.payload[0] in self.pointless_commands:
            App._collecter.throw(
                2003, line=self.line, keys={"command": self.payload[0]}
            )
            return True
        return False


@Dispatcher.register(token="from")
class SourceImage(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)
        self.is_too_long()
        self.has_no_tag()
        self.has_latest_tag()

    def is_too_long(self):
        # payload could be 1 item FROM image:tag
        # payload could be 3 items FROM image:tag AS thing

        param_count = len(self.payload)

        if param_count not in [1, 3]:
            App._collecter.throw(1002, line=self.line, keys={"command": self.payload})
            return True

        # additional checks
        if param_count == 3:
            if self.payload[1].upper() != "AS":
                App._collecter.throw(1005, line=self.line, keys={"command": "FROM",
                                                                 "specifier": "AS"})
                return True
        return False

    def has_no_tag(self):
        if ":" not in self.payload[0]:
            App._collecter.throw(2000, line=self.line, keys={"image": self.payload[0]})
            return True
        return False

    def has_latest_tag(self):
        if ":latest" in self.payload[0]:
            App._collecter.throw(2001, line=self.line)
            return True
        return False


@Dispatcher.register(token="user")
class User(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)

    def is_becoming_root(self):
        if self.payload[0] == "root":
            App._collecter.throw(2007, line=self.line)
            return True
        return False


@Dispatcher.register(token="workdir")
class Workdir(Token):
    def __init__(self, payload, line):
        Token.__init__(self, __class__, payload, line)

    def has_relative_path(self):
        if not payload[0].startswith("/"):
            App._collecter.throw(2004, line=self.line)
            return True
        return False
