import math


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def ease_in_out(t):
    t = clamp(float(t), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def ease_out_back(t, s=1.35):
    t = clamp(float(t), 0.0, 1.0) - 1.0
    return t * t * ((s + 1) * t + s) + 1


class OneEuro:
    def __init__(self, freq, min_cutoff=1.0, beta=0.03, d_cutoff=1.0):
        self.freq = float(freq)
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_prev = None
        self._dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff, freq):
        tau = 1.0 / (2.0 * math.pi * max(1e-6, cutoff))
        te = 1.0 / max(1e-6, freq)
        return 1.0 / (1.0 + tau / te)

    def reset(self):
        self._x_prev = None
        self._dx_prev = 0.0

    def __call__(self, x):
        x = float(x)
        if self._x_prev is None:
            self._x_prev = x
            return x
        dx = (x - self._x_prev) * self.freq
        ad = self._alpha(self.d_cutoff, self.freq)
        dx_hat = ad * dx + (1 - ad) * self._dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, self.freq)
        x_hat = a * x + (1 - a) * self._x_prev
        self._x_prev = x_hat
        self._dx_prev = dx_hat
        return x_hat
