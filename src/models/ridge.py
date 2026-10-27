import numpy as np


def fit(x, y, alpha):
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-8] = 1
    z = np.column_stack([np.ones(len(x)), (x - mean) / std])
    penalty = np.eye(z.shape[1]) * alpha
    penalty[0, 0] = 0
    coef = np.linalg.solve(z.T @ z + penalty, z.T @ y)
    return {"mean": mean, "std": std, "coef": coef}


def predict(model, x):
    z = np.column_stack([np.ones(len(x)), (x - model["mean"]) / model["std"]])
    return z @ model["coef"]


def save(model, path, horizon, alpha):
    np.savez(path, mean=model["mean"], std=model["std"], coef=model["coef"], horizon=horizon, alpha=alpha)

