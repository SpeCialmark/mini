import os
import click


@click.command()
@click.argument('files', nargs=-1, type=click.Path(exists=True))
def rename(files):
    for path in files:
        new_path = path.replace('1 (', '20180604_')
        new_path = new_path.replace(')', '')
        os.rename(path, new_path)
        print(os.path.basename(path) + ' -> ' + os.path.basename(new_path))


@click.group()
def cli():
    """
    Example:
    $python checkin_img.py rename ~/Pictures/exs/*
    $python checkin_img.py move ~/Pictures/exs/* ~/workoutprog/res/exs_image/G/
    """
    pass


cli.add_command(rename)


if __name__ == '__main__':
    cli()
