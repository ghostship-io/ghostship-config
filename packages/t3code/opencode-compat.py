"""Keep existing noninteractive OpenCode run launchers compatible with V2."""

import os
import sys


def translate(arguments):
    arguments = list(arguments)
    directory = None
    if arguments and arguments[0] == "run":
        index = 1
        while index < len(arguments):
            if arguments[index] == "--":
                break
            if arguments[index] == "--dir" and index + 1 < len(arguments):
                directory = arguments[index + 1]
                del arguments[index : index + 2]
                continue
            if arguments[index] == "--log-level" and index + 1 < len(arguments):
                arguments[index + 1] = arguments[index + 1].lower()
                index += 1
            index += 1
    return directory, arguments


if __name__ == "__main__":
    target, *arguments = sys.argv[1:]
    directory, arguments = translate(arguments)
    if directory is not None:
        os.chdir(directory)
    os.execv(target, [target, *arguments])
