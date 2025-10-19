import typer
from rich import print

app = typer.Typer(help="News Agent CLI")

@app.command()
def hello():
    """Confirm that the environment is working."""
    print("[bold green]Hello![/bold green] Your environment is ready.")

if __name__ == "__main__":
    app()
