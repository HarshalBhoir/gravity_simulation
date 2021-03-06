import time

import numpy as np
from cnf import (
    max_steps,
    col_threshold,
    move_without_render,
    t,
    drag_coeff,
    min_bodies,
    save_steps,
    path,
    log_path,
    do_log,
)
import cProfile

import pstats

from environment import V, X, M, COLOR, DO_LOCK, LOCK, WIDTH, HEIGHT
from datetime import datetime, timedelta

import json
import sqlite3
import numba


def main():
    now = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")

    # create database
    conn = sqlite3.connect(path.format(now))
    cur = conn.cursor()
    cur.execute("CREATE TABLE sim (ix INT PRIMARYKEY, x JSON, v JSON, m JSON, color JSON, x_pre JSON)")
    conn.commit()

    lock = LOCK
    n_bodies = M.shape[0]

    # Velocity
    v = np.copy(V)

    # Position
    x = np.copy(X)

    # Mass
    m = np.copy(M)

    # Color
    color = np.copy(COLOR)
    cp = np.copy

    @numba.njit
    def a(x, m, n_bodies):
        x_j = x.reshape(-1, 1, 2)
        x_i = x.reshape(1, -1, 2)
        d = x_j - x_i

        a_ = (m.reshape(-1, 1, 1) * (d)) / (np.sqrt(d[:, :, 0] ** 2 + d[:, :, 1] ** 2) ** 3).reshape(
            n_bodies, n_bodies, 1
        )
        for i in range(0, a_.shape[0]):
            a_[i, i] = 0
        return np.sum(a_, axis=0)

    # When two objects collide, their force and weight adds up
    @numba.njit
    def collision(m, p, v, n, lock, col_threshold):
        for i in numba.prange(n):
            if m[i] > 0:
                diff = p - p[i]
                r = m[i] ** (1 / 3)
                distance = np.arange(diff.shape[0])
                for j in numba.prange(diff.shape[0]):
                    distance[j] = (diff[j, 0] ** 2 + diff[j, 1] ** 2) ** .5
                collisions = (distance < (r * col_threshold)) & (m > 0)
                collisions[i] = False
                m_col = m[collisions]
                v_col = v[collisions]
                p_col = p[collisions]

                m[collisions] = 0

                m_i_pre = m[i]

                m[i] += np.sum(m_col)

                v[i] *= m_i_pre

                v[i] += np.sum(v_col * m_col.reshape(-1, 1), axis=0)

                v[i] /= m[i]

                p[i] *= m_i_pre
                p[i] += np.sum(p_col * m_col.reshape(-1, 1), axis=0)

                p[i] /= m[i]

                # if lock in collisions:
                #     lock = i

        return m, p, v, lock

    def sim_runge_kutter(m, x, v, step, n_bodies):
        k0 = step * v
        l0 = step * a(x, m, n_bodies)

        k1 = step * (v + l0 * 0.5)
        l1 = step * a(x + k0 * 0.5, m, n_bodies)

        k2 = step * (v + l1 * 0.5)
        l2 = step * a(x + l1 * 0.5, m, n_bodies)

        k3 = step * (v + l2)
        l3 = step * a(x + k2, m, n_bodies)
        x = x + (1 / 6) * (k0 + 2 * k1 + 2 * k2 + k3)

        v = v + (1.0 / 6) * (l0 + 2 * l1 + 2 * l2 + l3)

        return x, v

    def kill_empty(m, x, v, n):
        empty = m == 0
        m = m[~empty]
        x = x[~empty]
        v = v[~empty]
        n = np.sum(~empty)
        return m, x, v, n

    np.set_printoptions(suppress=True)

    start = time.time()
    last = start
    steps = 0
    try:
        while (steps < max_steps) and (n_bodies >= min_bodies):

            # collide objects
            m, x, v, _ = collision(m, x, v, n_bodies, lock, col_threshold)
            # remove mass=0 objects
            m, x, v, n_bodies = kill_empty(m, x, v, n_bodies)

            x_pre = cp(x)
            # simulate
            x, v = sim_runge_kutter(m, x, v, t, n_bodies)
            v = v * drag_coeff

            # change position of objects so locked object is always in the middle of the screen
            if DO_LOCK:
                x = x - x[lock] + (WIDTH / 2, HEIGHT / 2)
            # put state into database
            if steps % move_without_render == 0:
                cur.execute(
                    "INSERT INTO sim VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        steps,
                        json.dumps(x.astype(int).tolist()),
                        json.dumps(v.astype(int).tolist()),
                        json.dumps(m.astype(int).tolist()),
                        json.dumps(color.astype(int).tolist()),
                        json.dumps(x_pre.astype(int).tolist()),
                    ),
                )
            print(
                "{:>10} {} {} {}           ".format(
                    steps, timedelta(seconds=time.time() - last), timedelta(seconds=time.time() - start), n_bodies
                ),
                end="\r",
            )
            if do_log:
                with open(log_path.format(now), "a") as f:
                    f.write("{},{},{},{}\n".format(steps, time.time() - last, time.time(), n_bodies))
            last = time.time()
            steps += 1
            if steps % save_steps == 0:
                print("\nAutosaving...")
                conn.commit()
                print("Done!")

            # pause button
    finally:
        print("Saving...")
        conn.commit()
        print("Done!")
        conn.close()


cProfile.run("main()", "restats")

p = pstats.Stats("restats")
p.strip_dirs().sort_stats("time").print_stats(10)
