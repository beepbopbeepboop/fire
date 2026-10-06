def main():
    # Open file for writing
    f = open("test_output.txt", "w")

    # Write some content
    f.write("Hello from Mojo!\n")
    f.write("This is a test.\n")
    f.close()

    # Print confirmation
    print("File written successfully!")

main()
