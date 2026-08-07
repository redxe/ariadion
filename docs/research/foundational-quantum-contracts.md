# Foundational quantum contracts design evidence

**Documentation consulted:** 2026-08-07.

This record preserves foundational quantum-contract material as design evidence.
It is not an accepted implementation ADR. It does not claim new physics and does
not authorize semantics, compiler, runtime, or backend implementation changes.

The accepted current-state conclusion for Ariadion is:

Latent architectural risk and future optimizer proof obligation; no current
supported-path defect identified.

## Status and purpose

This note captures established quantum principles that Ariadion may eventually
express as explicit contracts, diagnostics, and proof obligations.

- scope: design evidence only;
- intent: preserve current facts separately from future recommendations;
- boundary: no implementation dates or milestone completion claims.

## Current Ariadion audit evidence

Current implementation facts from the accepted read-only audit boundaries:

- `packages/language/src/ariadion_language/angle.py` converts source units to
  radians and does not apply modulo-$2\pi$ normalization.
- `packages/daidalon/src/daidalon/compiler.py` lowers rotation angles directly,
  preserves logical-operation provenance, and shows no active optimizer/rewrite
  pass that equates phase-different operators.
- `packages/simulator/src/ariadion_simulator/statevector.py` executes retained
  `RX`/`RY`/`RZ` and `CX` operations directly.
- `packages/theonoe/src/theonoe/inspector.py` performs global-phase
  canonicalization for inspection comparison.
- `packages/runtime/src/ariadion_runtime/inspection.py` keeps that comparison
  inside the inspection pipeline.

Conclusion:

Latent architectural risk and future optimizer proof obligation; no current
supported-path defect identified.

## Pauli algebra and phase-context equivalence

Pauli identities:

$$
\sigma_i\sigma_j = \delta_{ij} I + i\,\epsilon_{ijk}\sigma_k
$$

$$
[\sigma_i,\sigma_j] = 2i\,\epsilon_{ijk}\sigma_k
$$

Axis-angle rotation:

$$
R_{\mathbf n}(\theta)=\exp\!\left(-i\theta\,\mathbf n\cdot\boldsymbol\sigma/2\right)
=\cos(\theta/2)I-i\sin(\theta/2)\,\mathbf n\cdot\boldsymbol\sigma
$$

$$
R_{\mathbf n}(2\pi)=-I
$$

$$
R_{\mathbf n}(4\pi)=I
$$

For an isolated closed state, $-I$ is observationally equivalent to $I$ up to
global phase. That equivalence is not generally safe once the operation is
controlled or embedded in interference-sensitive structure where global phase in
one branch becomes relative phase between branches.

Mathematical counterexample (proof obligation, not a claim about currently
exposed Ariadion controlled-rotation APIs):

- start control in $|+\rangle$;
- apply controlled-$(-I)$ to a target branch;
- control becomes

$$
|+\rangle\longrightarrow\frac{|0\rangle-|1\rangle}{\sqrt2}=| - \rangle;
$$

- final Hadamard on control yields measurement outcome 1;
- replacing controlled-$(-I)$ by controlled-$I$ yields outcome 0.

## Equivalence relations and optimizer proof obligations

Any future rewrite must declare which relation it preserves:

- matrix-exact equivalence: $U=V$ as operators;
- ray equivalence: states equal up to one global phase factor $e^{i\phi}$;
- observational equivalence: declared inputs, measurements, outputs, noise
  model, and tolerance yield equivalent reported behavior.

Required proof obligation:

- every optimization must state the preserved equivalence relation;
- every optimization must state whether rewritten operations may later become
  controlled or participate in interference contexts.

## Feynman coherence classes

$$
P(E)=\sum_r\left|\sum_{h\in C_r}A_h\right|^2
$$

Interpretation:

- amplitudes add within an indistinguishable coherence class $C_r$;
- probabilities add across distinguishable final records;
- unread environment records can still eliminate interference;
- path/history attribution depends on chosen basis and decomposition.

Bounded future Milestone 6 concept (design-only interference ledger):

- coherent alternatives;
- distinguishing record;
- cross term gained or lost;
- responsible measurement/noise/schedule event;
- declared basis and decomposition;
- explicit bound: no promise to enumerate exponentially many histories.

## Pauli-coordinate explanations

Single-qubit state and observable forms:

$$
\rho=\frac12\left(I+\mathbf r\cdot\boldsymbol\sigma\right)
$$

$$
A=a_0I+\mathbf a\cdot\boldsymbol\sigma
$$

$$
\operatorname{Tr}(\rho A)=a_0+\mathbf r\cdot\mathbf a
$$

$n$-qubit Pauli-string expansion:

$$
\rho=\frac{1}{2^n}\sum_{P\in\mathcal P_n}c_P P,
\qquad c_P=\operatorname{Tr}(P\rho)
$$

Affine channel representation:

$$
\mathbf r' = M\mathbf r + \mathbf t
$$

Pauli-transfer matrix representation:

$$
c' = R c,
\qquad
R_{ij}=\frac{1}{2^n}\operatorname{Tr}\!\left(P_i\,\mathcal E(P_j)\right)
$$

Deferred Theonoe explanation uses:

- distinguish coherent rotation, contraction, and translation;
- explain dephasing and amplitude damping;
- keep classical readout distortion separate from quantum-channel behavior;
- acknowledge worst-case $4^n$ storage growth.

## Symmetry and conserved-observable assertions

$$
[H,Q]=0\Rightarrow\frac{d\langle Q\rangle}{dt}=0
$$

$$
U^\dagger Q U = Q
$$

$$
\mathcal E^\dagger(Q)=Q
$$

Future report shape (design-only):

- parity;
- excitation number;
- stabilizers;
- problem-specific observables;
- first gate/schedule/noise event that breaks the invariant.

Distinction to preserve:

- user-declared invariants;
- mechanically proven invariants.

## Stabilizer and Pauli-frame protection vocabulary

Preserve as future planning vocabulary:

- stabilizer generators;
- logical operators;
- syndrome evidence;
- error classes;
- code distance;
- Pauli-frame updates;
- classical feed-forward;
- resource and noise assumptions.

Current boundary:

- no encoded-QEC implementation is authorized;
- no stabilizer backend is being introduced;
- no automatic backend selection is proposed.

## Choi and channel proof artifacts

Future channel-validation evidence should include:

- Kraus-completeness residual;
- Choi minimum eigenvalue;
- trace-preservation residual;
- declared numerical tolerance;
- model and derivation provenance.

## GKSL/Lindblad boundary

Markovian semigroup form:

$$
\frac{d\rho}{dt}
=
-\frac{i}{\hbar}[H,\rho]
+
\sum_k \gamma_k
\left(
L_k\rho L_k^\dagger
-\frac{1}{2}\{L_k^\dagger L_k,\rho\}
\right)
$$

In this Markovian semigroup representation, the dissipative rates satisfy
$\gamma_k \ge 0$.

$$
\mathcal E_t=e^{t\mathcal L}.
$$

Boundary statement:

- this is a Markovian-semigroup model;
- it is not a universal representation of non-Markovian noise.

## Periodicity taxonomy, geometric phase, Floquet, and Magnus

Distinguish:

- operator periodicity: $U(T)=I$;
- exact vector periodicity;
- ray periodicity up to $e^{i\chi}$;
- density/observable periodicity;
- Floquet recurrence and quasienergy structure.

Deferred research axes:

- Berry phase;
- Aharonov-Anandan phase;
- Floquet theory;
- Magnus expansion.

Boundary:

- phase-equivalence contracts can be specified now;
- periodic-Hamiltonian or pulse-level implementation must wait for explicit
  Hamiltonian/pulse semantics.

## Parameter sensitivity and assumptions

Hellmann-Feynman relation under exact-eigenstate and stationarity assumptions:

$$
\frac{\partial E_n(\lambda)}{\partial\lambda}
=
\left\langle n(\lambda)\left|\frac{\partial H(\lambda)}{\partial\lambda}\right|n(\lambda)\right\rangle
$$

Do not conflate with:

- parameter-shift rules;
- finite differences;
- adjoint differentiation;
- arbitrary time-dependent circuit differentiation.

## Deferred specialized research

Preserve as future specialized modules:

- fermionic antisymmetry and fermion-to-qubit mappings;
- Bell/CHSH diagnostics with shot and measurement-setting provenance;
- quasiprobability negativity as representation-dependent;
- reversible computation, uncomputation, and ancilla cleanup;
- representation-specialized families: stabilizer, tensor-network, sparse, and
  observable-only approaches.

## Ranked recommendation

1. Phase/equivalence contract.
2. Pauli-coordinate explanations.
3. Coherence-class debugger design.
4. Symmetry/conservation assertions.
5. Stabilizer and Pauli-frame protection vocabulary.
6. Choi/channel proof artifacts.
7. Lindblad generator boundary.
8. Geometric phase, Floquet, and Magnus support.
9. Hamiltonian sensitivity.
10. Specialized fermionic, Bell, and quasiprobability modules.

## Primary-source ledger

1. W. Pauli, ["On the Quantum Mechanics of Magnetic Electrons"](https://doi.org/10.1007/BF01397326), *Zeitschrift fur Physik* 43, 601-623 (1927), consulted 2026-08-07.
2. W. Pauli, [*General Principles of Quantum Mechanics*](https://doi.org/10.1007/978-3-642-61840-6), Springer, consulted 2026-08-07.
3. R. P. Feynman, R. B. Leighton, and M. Sands, [*The Feynman Lectures on Physics, Volume III*](https://www.feynmanlectures.caltech.edu/III_toc.html), Chapters 1, 3, 4, 11, and 17, consulted 2026-08-07.
4. R. P. Feynman, ["Space-Time Approach to Non-Relativistic Quantum Mechanics"](https://doi.org/10.1103/RevModPhys.20.367), *Reviews of Modern Physics* 20, 367-387 (1948), consulted 2026-08-07.
5. R. P. Feynman, ["Simulating Physics with Computers"](https://doi.org/10.1007/BF02650179), *International Journal of Theoretical Physics* 21, 467-488 (1982), consulted 2026-08-07.
6. R. P. Feynman, ["Forces in Molecules"](https://doi.org/10.1103/PhysRev.56.340), *Physical Review* 56, 340-343 (1939), consulted 2026-08-07.
7. E. Noether, ["Invariant Variation Problems"](https://arxiv.org/abs/physics/0503066), English translation record, consulted 2026-08-07.
8. M. V. Berry, ["Quantal phase factors accompanying adiabatic changes"](https://doi.org/10.1098/rspa.1984.0023), *Proceedings of the Royal Society A* 392, 45-57 (1984), consulted 2026-08-07.
9. Y. Aharonov and J. Anandan, ["Phase change during a cyclic quantum evolution"](https://doi.org/10.1103/PhysRevLett.58.1593), *Physical Review Letters* 58, 1593-1596 (1987), consulted 2026-08-07.
10. G. Floquet, ["Sur les equations differentielles lineaires a coefficients periodiques"](https://doi.org/10.24033/asens.220), *Annales scientifiques de l'Ecole Normale Superieure* 12, 47-88 (1883), consulted 2026-08-07.
11. W. Magnus, ["On the exponential solution of differential equations for a linear operator"](https://doi.org/10.1002/cpa.3160070404), *Communications on Pure and Applied Mathematics* 7, 649-673 (1954), consulted 2026-08-07.
12. G. Lindblad, ["On the generators of quantum dynamical semigroups"](https://doi.org/10.1007/BF01608499), *Communications in Mathematical Physics* 48, 119-130 (1976), consulted 2026-08-07.
13. V. Gorini, A. Kossakowski, and E. C. G. Sudarshan, ["Completely positive dynamical semigroups of N-level systems"](https://doi.org/10.1063/1.522979), *Journal of Mathematical Physics* 17, 821-825 (1976), consulted 2026-08-07.
14. M.-D. Choi, ["Completely positive linear maps on complex matrices"](https://doi.org/10.1016/0024-3795(75)90075-0), *Linear Algebra and its Applications* 10, 285-290 (1975), consulted 2026-08-07.
15. D. Gottesman, [*Stabilizer Codes and Quantum Error Correction*](https://arxiv.org/abs/quant-ph/9705052), PhD thesis preprint, consulted 2026-08-07.
16. J. S. Bell, ["On the Einstein Podolsky Rosen paradox"](https://doi.org/10.1103/PhysicsPhysiqueFizika.1.195), *Physics Physique Fizika* 1, 195-200 (1964), consulted 2026-08-07.
17. R. P. Feynman and A. R. Hibbs, *Quantum Mechanics and Path Integrals*, McGraw-Hill (1965), supplementary canonical source, consulted 2026-08-07.
18. D. Gottesman, ["The Heisenberg Representation of Quantum Computers"](https://arxiv.org/abs/quant-ph/9807006), supplementary preprint, consulted 2026-08-07.

## Explicit non-goals

- no claim of new physics;
- no quantum-semantics change;
- no compiler optimization implementation;
- no new simulator backend;
- no automatic backend selection;
- no encoded-QEC implementation;
- no pulse or time-dependent Hamiltonian contract;
- no persistence change;
- no implementation dates.
