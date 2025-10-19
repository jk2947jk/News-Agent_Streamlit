import typer
from rich import print

# Create the Typer application
app = typer.Typer(help="News Agent CLI")

# Define a command called 'hello'
@app.command()
def hello():
    """Confirm that the environment is working."""
    print("[bold green]Hello![/bold green] Your environment is ready.")

# Run the application when executed directly
if __name__ == "__main__":
    app()
