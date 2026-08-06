from ariadion import Program, run


program = Program(1, name="phase")
program.h(0).z(0)

if __name__ == "__main__":
    result = run(program)
    print(result.circuit)
    print()
    print(result.report)
