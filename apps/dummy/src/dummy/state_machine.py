from enum import Enum


class State(str, Enum):
    SLEEP = "SLEEP"
    AWAKE = "AWAKE"
    IDLE = "IDLE"
    FOLLOW = "FOLLOW"
    SEARCH = "SEARCH"
    ATTENTIVE = "ATTENTIVE"
