from strands import Agent


def main():
    agent = Agent()

    response = agent("Say hello in one short sentence.")

    print("\nStrands response:")
    print(response)


if __name__ == "__main__":
    main()