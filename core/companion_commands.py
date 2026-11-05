"""Exact, low-risk commands that only affect the companion, never other apps."""
import re


def companion_command(text):
    text = text.strip().strip("。！!～~ ")
    text = re.sub(r"^(?:小乐|蕾缪乐)[，,\s]*", "", text)
    text = re.sub(r"^(?:请|麻烦你)", "", text).strip()
    text = re.sub(r"[吧啦呀]$", "", text).strip()
    commands = {
        "smaller": r"(?:你|小乐)?(?:变小|缩小)(?:一点|点|一些)?",
        "larger": r"(?:你|小乐)?(?:变大|放大)(?:一点|点|一些)?",
        "reset_size": r"(?:恢复|还原)(?:默认|原来|正常)(?:大小|尺寸)",
        "quiet": r"安静陪我|安静陪着我|先别主动说话|开启勿扰|进入勿扰模式",
        "talk": r"恢复主动聊天|恢复主动说话|关闭勿扰|退出勿扰模式",
        "left": r"(?:你|小乐)?(?:靠|挪到|移到|待在)(?:屏幕)?左(?:边|下角)",
        "right": r"(?:你|小乐)?(?:靠|挪到|移到|待在)(?:屏幕)?右(?:边|下角)",
    }
    for name, pattern in commands.items():
        if re.fullmatch(pattern, text):
            return name
    return None


def first_result_requested(text):
    if re.search(r"不要|不用|不许|别|如果|假如|比如|[“”‘’\"'`「」]", text):
        return False
    return bool(re.search(r"(?:打开|点开|点击|进入).{0,4}第[一1](?:条|个).{0,4}(?:结果|链接|词条)", text))
