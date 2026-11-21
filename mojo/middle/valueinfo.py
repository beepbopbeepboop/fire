"""The per-function facts about WORDS: which `int64_t` values are not plain ints.

An `int64_t` in this backend is an int, a pointer, a boxed float, a tagged
None/str, or an erased struct pointer, all at once (doc/GIR.md stage 5b). Six
name-keyed sets record which of those a lowered value may be. They used to be
six unrelated attributes of the generator, created in three places and saved
and restored by twelve `FuncState` fields. `WordFacts` owns them, so there is
ONE object per function body to create, save and restore.

Keys are SSA temp / variable names, which repeat across functions, so a
`WordFacts` is per function body (`_reset_func` makes a fresh one).

The generator keeps the six historical names (`gen._boxed_vals`, ...) bound to
the SAME set objects (`bind`), so readers and writers did not have to change in
the step that introduced this class.
"""


class WordFacts:
    def __init__(self):
        # values from `mojo_list_get_boxed`: may be a heap box (a float)
        self.boxed: set = set()
        # the subset of `boxed` that is a tagged generator word
        self.tagged: set = set()
        # values that are a dynamic word (int / str / None) of unknown kind
        self.dyn: set = set()
        # values PROVEN to be integers, never a pointer (see `_char_to_cstr`)
        self.int_word: set = set()
        # lists / values whose slots carry per-slot kinds (struct.unpack ...)
        self.maybe_kinds: set = set()
        # call results holding a container whose kind the caller cannot know
        self.boxed_container: set = set()

    def bind(self, gen) -> None:
        """Point the generator's six historical names at these sets."""
        gen._boxed_vals = self.boxed
        gen._tagged_word_vals = self.tagged
        gen._dyn_word_vals = self.dyn
        gen._int_word_vals = self.int_word
        gen._maybe_kinds_vals = self.maybe_kinds
        gen._boxed_container_vals = self.boxed_container

    def snapshot(self) -> list:
        """Copies of the three sets a nested body empties and a restore refills
        (the other three are replaced wholesale by a fresh `WordFacts`)."""
        return [set(self.boxed), set(self.tagged), set(self.int_word)]

    def restore_snapshot(self, snap: list) -> None:
        self.boxed.clear()
        for _k in snap[0]:
            self.boxed.add(_k)
        self.tagged.clear()
        for _k in snap[1]:
            self.tagged.add(_k)
        self.int_word.clear()
        for _k in snap[2]:
            self.int_word.add(_k)
