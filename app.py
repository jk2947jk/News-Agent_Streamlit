Set-Content app.py @"
from rich import print
import typer

app = typer.Typer(help="News Agent CLI")

@app.command()
def hello():
    print("[bold green]Hello![/bold green] Your environment is ready.")

if __name__ == "__main__":
    app()
"@
