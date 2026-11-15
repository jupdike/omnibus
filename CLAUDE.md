# The Complete Sherlock Holmes

`./holmes/`

Standard Ebooks lists the 9 books that comprise the Sherlock Holmes canon, 4 novels, 5 short story collections (56 shorts stories total, I believe):
* https://standardebooks.org/collections/sherlock-holmes
This is also the ordering that we want, in the new Table of Contents.

For example the first link on that page:
* https://standardebooks.org/ebooks/arthur-conan-doyle/a-study-in-scarlet

And from that page we have a direct download link to the "compatible epub":
* https://standardebooks.org/ebooks/arthur-conan-doyle/a-study-in-scarlet/downloads/arthur-conan-doyle_a-study-in-scarlet.epub

Let's make a new omnibus of The Complete Sherlock Holmes (that is the title we want, in any metadata)

## Omnibus Epub

0. I made a large cover image for the new omnibus, input/sherlock-holmes-complete-cover.jpg
1. Download the 9 Epubs into the input/ folder
2. Determine the structure for a new Epub (folder / files) and reuse as much structure, CSS, technology (popup notes or table of contents, etc.) as possible. These epubs respect dark mode, scaling, user Epub reader font settings, etc. and are known to be high-quality in terms of editorial, all of that.
3. Create new files as needed (xhtml and css, mostly, I believe) and copy all older resources into a new build/ folder
4. Build me an epub file that I can test
5. Bonus: it might be nice to have reusable Python scripts that can be used to concatenate other sets of epubs, for example William Shakespeare, into new omnibus Epubs. If so, those Python scripts can go in a new src/ folder

Last note: if you need epub tools of some kind, Standard Ebooks Github repos have tons of useful tools, but that may require spinning up a Linux VM or Docker to get the dependencies, not something I really want to have to do, just know that other epub-related commandline tools might be available (for example, to check the final Epub file, etc.)

Note that I'm less interested in creating a repo for other people or supporting Kobo, Kindle, etc. For my purposes (Apple platforms) the compatible Epub is enough for me.
