from blessed import Terminal

term = Terminal()

print(term.home + term.clear + term.move_y(0))
print(term.black_on_darkkhaki(term.center('Picciuli - Money Manager by Antonio Barba')))

with term.cbreak(), term.hidden_cursor():
    inp = term.inkey()

if inp == 'a':
    print('a is pressed')


print(term.move_down(2) + 'You pressed ' + term.bold(repr(inp)))


