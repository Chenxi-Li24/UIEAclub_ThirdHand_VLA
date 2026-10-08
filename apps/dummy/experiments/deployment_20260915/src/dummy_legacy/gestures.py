class GestureLibrary:
    def __init__(self, config):
        self.config = config
        self.gestures = config.get("gestures", {})

    def get(self, name):
        if name not in self.gestures:
            raise KeyError(name)
        return self.gestures[name]

    def names(self):
        return sorted(self.gestures)
