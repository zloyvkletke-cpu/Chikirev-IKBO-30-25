"""VFS shell emulator — вариант 26 (GUI).

Графический эмулятор UNIX-подобной оболочки над виртуальной
файловой системой. VFS загружается из директории в память
и там же изменяется.
"""

import argparse
import getpass
import hashlib
import os
import platform
import re
import shlex
import sys
import tkinter as tk

ENV_RE = re.compile(r"\$(\w+|\{[^}]+\})")


class ShellExit(Exception):
    """Сигнал выхода из оболочки."""


def load_vfs(path):
    """Прочитать директорию с диска в память.

    Возвращает (имя, дерево), где дерево — словарь
    абсолютный_путь -> {"is_dir", "content", "owner"}.
    """
    if not os.path.isdir(path):
        raise ValueError(f"not a directory: {path}")
    name = os.path.basename(os.path.abspath(path)) or "root"
    tree = {"/": {"is_dir": True, "content": b"", "owner": "user"}}
    for dirpath, dirnames, filenames in os.walk(path):
        rel = os.path.relpath(dirpath, path)
        prefix = "/" if rel == "." else "/" + rel.replace(os.sep, "/") + "/"
        for d in dirnames:
            tree[prefix + d] = {"is_dir": True, "content": b"", "owner": "user"}
        for f in filenames:
            with open(os.path.join(dirpath, f), "rb") as fh:
                tree[prefix + f] = {
                    "is_dir": False, "content": fh.read(), "owner": "user",
                }
    return name, tree


def vfs_hash(tree):
    """SHA-256 по всему дереву VFS."""
    h = hashlib.sha256()
    for p in sorted(tree):
        h.update(p.encode())
        h.update(b"D" if tree[p]["is_dir"] else b"F")
        h.update(tree[p]["owner"].encode())
        h.update(tree[p]["content"])
    return h.hexdigest()


def expand_env(text):
    """Заменить $VAR и ${VAR} значениями из окружения хоста."""
    return ENV_RE.sub(lambda m: os.environ.get(m.group(1).strip("{}"), ""), text)


def parse(line):
    """Разобрать строку на (имя, аргументы). Поддержка кавычек и #."""
    line = line.split("#", 1)[0].strip()
    if not line:
        return "", []
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"parse error: {exc}") from exc
    return parts[0], [expand_env(p) for p in parts[1:]]


def norm(base, path):
    """Нормализовать путь: убрать '.', обработать '..' и ведущий '/'."""
    parts = [] if path.startswith("/") else [p for p in base.split("/") if p]
    for p in path.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
        else:
            parts.append(p)
    return "/" + "/".join(parts) if parts else "/"


# ---------- Команды ----------

def cmd_ls(state, args):
    """Показать содержимое директории или имя файла."""
    if len(args) > 1:
        raise ValueError("too many arguments")
    path = norm(state["cwd"], args[0] if args else ".")
    if path not in state["tree"]:
        raise ValueError(f"no such file or directory: {args[0] if args else '.'}")
    if not state["tree"][path]["is_dir"]:
        return path.rsplit("/", 1)[-1]
    prefix = path.rstrip("/") + "/"
    names = sorted({p[len(prefix):].split("/")[0]
                    for p in state["tree"]
                    if p != path and p.startswith(prefix)})
    return "  ".join(names)


def cmd_cd(state, args):
    """Сменить текущую директорию."""
    if len(args) > 1:
        raise ValueError("too many arguments")
    path = norm(state["cwd"], args[0] if args else "/")
    if path not in state["tree"]:
        raise ValueError(f"no such file or directory: {args[0] if args else '/'}")
    if not state["tree"][path]["is_dir"]:
        raise ValueError(f"not a directory: {args[0]}")
    state["cwd"] = path
    return ""


def cmd_who(state, args):
    """Показать владельцев файлов и текущего пользователя."""
    if args:
        raise ValueError("takes no arguments")
    owners = {state["user"]} | {n["owner"] for n in state["tree"].values()}
    return "\n".join(sorted(owners))


def cmd_wc(state, args):
    """Строки / слова / байты для каждого файла."""
    if not args:
        raise ValueError("missing file operand")
    rows = []
    for a in args:
        path = norm(state["cwd"], a)
        node = state["tree"].get(path)
        if node is None or node["is_dir"]:
            raise ValueError(f"{a}: not a file")
        text = node["content"].decode("utf-8", errors="replace")
        rows.append(f"{text.count(chr(10)):>4} {len(text.split()):>4} "
                    f"{len(node['content']):>5} {path.rsplit('/', 1)[-1]}")
    return "\n".join(rows)


def cmd_chown(state, args):
    """Сменить владельца одного или нескольких узлов (в памяти)."""
    if len(args) < 2:
        raise ValueError("usage: chown <owner> <path> [<path> ...]")
    for a in args[1:]:
        path = norm(state["cwd"], a)
        if path not in state["tree"]:
            raise ValueError(f"no such file or directory: {a}")
        state["tree"][path]["owner"] = args[0]
    return ""


def cmd_vfs_info(state, args):
    """Показать имя VFS и SHA-256 её содержимого."""
    if args:
        raise ValueError("takes no arguments")
    return f"name: {state['vfs_name']}\nhash: {vfs_hash(state['tree'])}"


COMMANDS = {
    "ls": cmd_ls, "cd": cmd_cd, "who": cmd_who, "wc": cmd_wc,
    "chown": cmd_chown, "vfs-info": cmd_vfs_info,
}


def prompt_str(state):
    """Собрать приглашение из данных реальной ОС."""
    cwd = "~" if state["cwd"] == "/" else "~" + state["cwd"]
    return f"{state['user']}@{state['host']}:{cwd}$"


def run_line(state, line):
    """Выполнить строку. Возвращает (вывод, is_error)."""
    name, args = parse(line)
    if not name:
        return "", False
    if name == "exit":
        raise ShellExit()
    handler = COMMANDS.get(name)
    if handler is None:
        return f"{name}: command not found", True
    try:
        return handler(state, args), False
    except ValueError as exc:
        return f"{name}: {exc}", True


# ---------- Графический интерфейс ----------

class App:
    """Окно эмулятора: область вывода, поле ввода и приглашение."""

    def __init__(self, root, state, script):
        self.state = state
        self.root = root
        root.title(f"VFS Shell — {state['vfs_name']}")
        root.geometry("820x520")

        self.output = tk.Text(root, wrap="word", state="disabled",
                              font=("Consolas", 10))
        self.output.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        frame = tk.Frame(root)
        frame.pack(fill="x", padx=6, pady=6)

        self.prompt_var = tk.StringVar()
        tk.Label(frame, textvariable=self.prompt_var,
                 font=("Consolas", 10)).pack(side="left")

        self.entry = tk.Entry(frame, font=("Consolas", 10))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.focus_set()

        self.write(f"[debug] vfs    = {state['vfs_name']}")
        self.write(f"[debug] script = {script}")
        self.write(f"[debug] vfs.hash = {vfs_hash(state['tree'])}")
        self.update_prompt()

        if script:
            self.run_script(script)

    def update_prompt(self):
        """Обновить приглашение в нижней строке."""
        self.prompt_var.set(prompt_str(self.state) + " ")

    def write(self, text):
        """Дописать строку в область вывода."""
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def on_enter(self, _event):
        """Обработать нажатие Enter в поле ввода."""
        line = self.entry.get()
        self.entry.delete(0, "end")
        self.write(f"{prompt_str(self.state)} {line}")
        try:
            out, _ = run_line(self.state, line)
        except ShellExit:
            self.root.destroy()
            return
        if out:
            self.write(out)
        self.update_prompt()

    def run_script(self, path):
        """Выполнить стартовый скрипт до первой ошибки."""
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:
            self.write(f"cannot run script: {exc}")
            return
        for raw in lines:
            line = raw.rstrip("\n")
            self.write(f"{prompt_str(self.state)} {line}")
            try:
                out, err = run_line(self.state, line)
            except ShellExit:
                self.root.destroy()
                return
            if out:
                self.write(out)
            if err:
                self.write("startup script stopped on error")
                return


# ---------- Точка входа ----------

def main(argv=None):
    """Запустить приложение."""
    ap = argparse.ArgumentParser(prog="vfs-shell")
    ap.add_argument("--vfs", help="путь к директории с исходной VFS")
    ap.add_argument("--script", help="путь к стартовому скрипту")
    args = ap.parse_args(argv)

    if args.vfs:
        try:
            name, tree = load_vfs(args.vfs)
        except (OSError, ValueError) as exc:
            root = tk.Tk()
            root.title("VFS Shell — error")
            tk.Label(root, text=f"failed to load VFS:\n{exc}",
                     font=("Segoe UI", 11)).pack(padx=30, pady=30)
            tk.Button(root, text="Закрыть",
                      command=root.destroy).pack(pady=(0, 20))
            root.mainloop()
            return 1
    else:
        name = "vfs"
        tree = {"/": {"is_dir": True, "content": b"", "owner": "user"}}

    state = {
        "vfs_name": name, "tree": tree, "cwd": "/",
        "user": getpass.getuser(), "host": platform.node() or "localhost",
    }

    root = tk.Tk()
    App(root, state, args.script)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())