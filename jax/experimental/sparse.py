# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import partial
import textwrap

import scipy.sparse.linalg
import jax.numpy as jnp
import numpy as np
from jax.numpy.lax_numpy import _wraps
from .. import lax


def _vdot(x, y):
  return jnp.vdot(x, y, precision=lax.Precision.HIGHEST)


def _identity(x):
  return x


def _cg_solve(A, b, x0=None, *, maxiter, tol=1e-5, atol=0.0, M=_identity):
  # tolerance handling uses the "non-legacy" behavior of scipy.sparse.linalg.cg
  bs = _vdot(b, b)
  atol2 = jnp.maximum(tol ** 2 * bs, atol ** 2)

  # https://en.wikipedia.org/wiki/Conjugate_gradient_method#The_preconditioned_conjugate_gradient_method

  def cond_fun(value):
    x, r, gamma, p, k = value
    rs = gamma if M is _identity else _vdot(r, r)
    return (rs > atol2) & (k < maxiter)

  def body_fun(value):
    x, r, gamma, p, k = value
    Ap = A(p)
    alpha = gamma / _vdot(p, Ap)
    x_ = x + alpha * p
    r_ = r - alpha * Ap
    z_ = M(r_)
    gamma_ = _vdot(r_, z_)
    beta_ = gamma_ / gamma
    p_ = z_ + beta_ * p
    return x_, r_, gamma_, p_, k + 1

  r0 = b - A(x0)
  p0 = z0 = M(r0)
  gamma0 = _vdot(r0, z0)
  initial_value = (x0, r0, gamma0, p0, 0)

  x_final, *_ = lax.while_loop(cond_fun, body_fun, initial_value)

  return x_final


@_wraps(scipy.sparse.linalg.cg,
    lax_description=textwrap.dedent("""\
        Unlike scipy.sparse.linalg.cg, the linear operator ``A`` to invert and
        the optional preconditioner ``M`` should be a functions that returns a
        matrix-vector product, not a LinearOperator. Also, the return code
        ``info`` is currently always fixed at 0.
        """))
def cg(A, b, x0=None, *, tol=1e-5, atol=0.0, maxiter=None, M=None):
  if x0 is None:
    x0 = jnp.zeros_like(b)

  if maxiter is None:
    maxiter = 10 * len(b)  # copied from scipy

  if M is None:
    M = _identity

  if x0.shape != b.shape:
    raise ValueError(
        f'x0 and b must have matching shape: {x0.shape} vs {b.shape}')
  if b.ndim != 1:
    raise ValueError(
        f'b must be one-dimensional, but has shape {b.shape}')

  cg_solve = partial(
      _cg_solve, x0=x0, tol=tol, atol=atol, maxiter=maxiter, M=M)
  x = lax.custom_linear_solve(A, b, cg_solve, symmetric=True)
  info = 0  # TODO(shoyer): return the real iteration count here
  return x, info
