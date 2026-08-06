from ariadion import Program, deg, rad, run, turns


program = Program(3, name="rotations")
program.rx(0, deg(190))
program.ry(1, rad(2))
program.rz(2, turns(0.25))

if __name__ == "__main__":
    result = run(program)
    print(result.circuit)
    print()
    print(result.report)
