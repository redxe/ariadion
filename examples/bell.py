from ariadion import Program, run


program = Program(2, name="bell")
program.h(0).cx(0, 1)

if __name__ == "__main__":
    result = run(program)
    print(result.circuit)
    print()
    print(result.report)
