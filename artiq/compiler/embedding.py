"""
The :class:`Stitcher` class allows to transparently combine compiled
Python code and Python code executed on the host system: it resolves
the references to the host objects and translates the functions
annotated as ``@kernel`` when they are referenced.
"""

import os, re, linecache, inspect, textwrap
from collections import OrderedDict, defaultdict

from pythonparser import ast, algorithm, source, diagnostic, parse_buffer

from . import types, builtins, asttyped, prelude
from .transforms import ASTTypedRewriter, Inferencer, IntMonomorphizer


class ObjectMap:
    def __init__(self):
        self.current_key = 0
        self.forward_map = {}
        self.reverse_map = {}

    def store(self, obj_ref):
        obj_id = id(obj_ref)
        if obj_id in self.reverse_map:
            return self.reverse_map[obj_id]

        self.current_key += 1
        self.forward_map[self.current_key] = obj_ref
        self.reverse_map[obj_id] = self.current_key
        return self.current_key

    def retrieve(self, obj_key):
        return self.forward_map[obj_key]

class ASTSynthesizer:
    def __init__(self, type_map, value_map, quote_function=None, expanded_from=None):
        self.source = ""
        self.source_buffer = source.Buffer(self.source, "<synthesized>")
        self.type_map, self.value_map = type_map, value_map
        self.quote_function = quote_function
        self.expanded_from = expanded_from

    def finalize(self):
        self.source_buffer.source = self.source
        return self.source_buffer

    def _add(self, fragment):
        range_from   = len(self.source)
        self.source += fragment
        range_to     = len(self.source)
        return source.Range(self.source_buffer, range_from, range_to,
                            expanded_from=self.expanded_from)

    def quote(self, value):
        """Construct an AST fragment equal to `value`."""
        if value is None:
            typ = builtins.TNone()
            return asttyped.NameConstantT(value=value, type=typ,
                                          loc=self._add(repr(value)))
        elif value is True or value is False:
            typ = builtins.TBool()
            return asttyped.NameConstantT(value=value, type=typ,
                                          loc=self._add(repr(value)))
        elif isinstance(value, (int, float)):
            if isinstance(value, int):
                typ = builtins.TInt()
            elif isinstance(value, float):
                typ = builtins.TFloat()
            return asttyped.NumT(n=value, ctx=None, type=typ,
                                 loc=self._add(repr(value)))
        elif isinstance(value, str):
            return asttyped.StrT(s=value, ctx=None, type=builtins.TStr(),
                                 loc=self._add(repr(value)))
        elif isinstance(value, list):
            begin_loc = self._add("[")
            elts = []
            for index, elt in enumerate(value):
                elts.append(self.quote(elt))
                if index < len(value) - 1:
                    self._add(", ")
            end_loc   = self._add("]")
            return asttyped.ListT(elts=elts, ctx=None, type=builtins.TList(),
                                  begin_loc=begin_loc, end_loc=end_loc,
                                  loc=begin_loc.join(end_loc))
        elif inspect.isfunction(value) or inspect.ismethod(value):
            function_name, function_type = self.quote_function(value, self.expanded_from)
            return asttyped.NameT(id=function_name, ctx=None, type=function_type,
                                  loc=self._add(repr(value)))
        else:
            quote_loc   = self._add('`')
            repr_loc    = self._add(repr(value))
            unquote_loc = self._add('`')
            loc         = quote_loc.join(unquote_loc)

            if isinstance(value, type):
                typ = value
            else:
                typ = type(value)

            if typ in self.type_map:
                instance_type, constructor_type = self.type_map[typ]
            else:
                instance_type = types.TInstance("{}.{}".format(typ.__module__, typ.__name__))
                instance_type.attributes['__objectid__'] = builtins.TInt(types.TValue(32))

                constructor_type = types.TConstructor(instance_type)
                constructor_type.attributes['__objectid__'] = builtins.TInt(types.TValue(32))
                instance_type.constructor = constructor_type

                self.type_map[typ] = instance_type, constructor_type

            if isinstance(value, type):
                self.value_map[constructor_type].append((value, loc))
                return asttyped.QuoteT(value=value, type=constructor_type,
                                       loc=loc)
            else:
                self.value_map[instance_type].append((value, loc))
                return asttyped.QuoteT(value=value, type=instance_type,
                                       loc=loc)

    def call(self, function_node, args, kwargs):
        """
        Construct an AST fragment calling a function specified by
        an AST node `function_node`, with given arguments.
        """
        arg_nodes   = []
        kwarg_nodes = []
        kwarg_locs  = []

        name_loc       = self._add(function_node.name)
        begin_loc      = self._add("(")
        for index, arg in enumerate(args):
            arg_nodes.append(self.quote(arg))
            if index < len(args) - 1:
                         self._add(", ")
        if any(args) and any(kwargs):
                         self._add(", ")
        for index, kw in enumerate(kwargs):
            arg_loc    = self._add(kw)
            equals_loc = self._add("=")
            kwarg_locs.append((arg_loc, equals_loc))
            kwarg_nodes.append(self.quote(kwargs[kw]))
            if index < len(kwargs) - 1:
                         self._add(", ")
        end_loc        = self._add(")")

        return asttyped.CallT(
            func=asttyped.NameT(id=function_node.name, ctx=None,
                                type=function_node.signature_type,
                                loc=name_loc),
            args=arg_nodes,
            keywords=[ast.keyword(arg=kw, value=value,
                                  arg_loc=arg_loc, equals_loc=equals_loc,
                                  loc=arg_loc.join(value.loc))
                      for kw, value, (arg_loc, equals_loc)
                       in zip(kwargs, kwarg_nodes, kwarg_locs)],
            starargs=None, kwargs=None,
            type=types.TVar(),
            begin_loc=begin_loc, end_loc=end_loc, star_loc=None, dstar_loc=None,
            loc=name_loc.join(end_loc))

    def assign_local(self, var_name, value):
        name_loc   = self._add(var_name)
        _          = self._add(" ")
        equals_loc = self._add("=")
        _          = self._add(" ")
        value_node = self.quote(value)

        var_node   = asttyped.NameT(id=var_name, ctx=None, type=value_node.type,
                                    loc=name_loc)

        return ast.Assign(targets=[var_node], value=value_node,
                          op_locs=[equals_loc], loc=name_loc.join(value_node.loc))

    def assign_attribute(self, obj, attr_name, value):
        obj_node   = self.quote(obj)
        dot_loc    = self._add(".")
        name_loc   = self._add(attr_name)
        _          = self._add(" ")
        equals_loc = self._add("=")
        _          = self._add(" ")
        value_node = self.quote(value)

        attr_node  = asttyped.AttributeT(value=obj_node, attr=attr_name, ctx=None,
                                         type=value_node.type,
                                         dot_loc=dot_loc, attr_loc=name_loc,
                                         loc=obj_node.loc.join(name_loc))

        return ast.Assign(targets=[attr_node], value=value_node,
                          op_locs=[equals_loc], loc=name_loc.join(value_node.loc))

class StitchingASTTypedRewriter(ASTTypedRewriter):
    def __init__(self, engine, prelude, globals, host_environment, quote):
        super().__init__(engine, prelude)
        self.globals = globals
        self.env_stack.append(self.globals)

        self.host_environment = host_environment
        self.quote = quote

    def visit_Name(self, node):
        typ = super()._try_find_name(node.id)
        if typ is not None:
            # Value from device environment.
            return asttyped.NameT(type=typ, id=node.id, ctx=node.ctx,
                                  loc=node.loc)
        else:
            # Try to find this value in the host environment and quote it.
            if node.id in self.host_environment:
                return self.quote(self.host_environment[node.id], node.loc)
            else:
                diag = diagnostic.Diagnostic("fatal",
                    "name '{name}' is not bound to anything", {"name":node.id},
                    node.loc)
                self.engine.process(diag)

class StitchingInferencer(Inferencer):
    def __init__(self, engine, value_map, quote):
        super().__init__(engine)
        self.value_map = value_map
        self.quote = quote

    def visit_AttributeT(self, node):
        self.generic_visit(node)
        object_type = node.value.type.find()

        # The inferencer can only observe types, not values; however,
        # when we work with host objects, we have to get the values
        # somewhere, since host interpreter does not have types.
        # Since we have categorized every host object we quoted according to
        # its type, we now interrogate every host object we have to ensure
        # that we can successfully serialize the value of the attribute we
        # are now adding at the code generation stage.
        #
        # FIXME: We perform exhaustive checks of every known host object every
        # time an attribute access is visited, which is potentially quadratic.
        # This is done because it is simpler than performing the checks only when:
        #   * a previously unknown attribute is encountered,
        #   * a previously unknown host object is encountered;
        # which would be the optimal solution.
        for object_value, object_loc in self.value_map[object_type]:
            if not hasattr(object_value, node.attr):
                note = diagnostic.Diagnostic("note",
                    "attribute accessed here", {},
                    node.loc)
                diag = diagnostic.Diagnostic("error",
                    "host object does not have an attribute '{attr}'",
                    {"attr": node.attr},
                    object_loc, notes=[note])
                self.engine.process(diag)
                return

            # Figure out what ARTIQ type does the value of the attribute have.
            # We do this by quoting it, as if to serialize. This has some
            # overhead (i.e. synthesizing a source buffer), but has the advantage
            # of having the host-to-ARTIQ mapping code in only one place and
            # also immediately getting proper diagnostics on type errors.
            attr_value = getattr(object_value, node.attr)
            if (inspect.ismethod(attr_value) and hasattr(attr_value.__func__, 'artiq_embedded')
                    and types.is_instance(object_type)):
                # In cases like:
                #     class c:
                #         @kernel
                #         def f(self): pass
                # we want f to be defined on the class, not on the instance.
                attributes = object_type.constructor.attributes
                attr_value = attr_value.__func__
            else:
                attributes = object_type.attributes

            ast = self.quote(attr_value, None)

            def proxy_diagnostic(diag):
                note = diagnostic.Diagnostic("note",
                    "expanded from here while trying to infer a type for an"
                    " attribute '{attr}' of a host object",
                    {"attr": node.attr},
                    node.loc)
                diag.notes.append(note)

                self.engine.process(diag)

            proxy_engine = diagnostic.Engine()
            proxy_engine.process = proxy_diagnostic
            Inferencer(engine=proxy_engine).visit(ast)
            IntMonomorphizer(engine=proxy_engine).visit(ast)

            if node.attr not in attributes:
                # We just figured out what the type should be. Add it.
                attributes[node.attr] = ast.type
            elif attributes[node.attr] != ast.type:
                # Does this conflict with an earlier guess?
                printer = types.TypePrinter()
                diag = diagnostic.Diagnostic("error",
                    "host object has an attribute of type {typea}, which is"
                    " different from previously inferred type {typeb}",
                    {"typea": printer.name(ast.type),
                     "typeb": printer.name(attributes[node.attr])},
                    object_loc)
                self.engine.process(diag)

        super().visit_AttributeT(node)

class TypedtreeHasher(algorithm.Visitor):
    def generic_visit(self, node):
        def freeze(obj):
            if isinstance(obj, ast.AST):
                return self.visit(obj)
            elif isinstance(obj, types.Type):
                return hash(obj.find())
            else:
                # We don't care; only types change during inference.
                pass

        fields = node._fields
        if hasattr(node, '_types'):
            fields = fields + node._types
        return hash(tuple(freeze(getattr(node, field_name)) for field_name in fields))

class Stitcher:
    def __init__(self, engine=None):
        if engine is None:
            self.engine = diagnostic.Engine(all_errors_are_fatal=True)
        else:
            self.engine = engine

        self.name = ""
        self.typedtree = []
        self.inject_at = 0
        self.prelude = prelude.globals()
        self.globals = {}

        self.functions = {}

        self.object_map = ObjectMap()
        self.type_map = {}
        self.value_map = defaultdict(lambda: [])

    def stitch_call(self, function, args, kwargs):
        function_node = self._quote_embedded_function(function)
        self.typedtree.append(function_node)

        # We synthesize source code for the initial call so that
        # diagnostics would have something meaningful to display to the user.
        synthesizer = self._synthesizer()
        call_node = synthesizer.call(function_node, args, kwargs)
        synthesizer.finalize()
        self.typedtree.append(call_node)

    def finalize(self):
        inferencer = StitchingInferencer(engine=self.engine,
                                         value_map=self.value_map,
                                         quote=self._quote)
        hasher = TypedtreeHasher()

        # Iterate inference to fixed point.
        old_typedtree_hash = None
        while True:
            inferencer.visit(self.typedtree)
            typedtree_hash = hasher.visit(self.typedtree)

            if old_typedtree_hash == typedtree_hash:
                break
            old_typedtree_hash = typedtree_hash

        # For every host class we embed, add an appropriate constructor
        # as a global. This is necessary for method lookup, which uses
        # the getconstructor instruction.
        for instance_type, constructor_type in list(self.type_map.values()):
            # Do we have any direct reference to a constructor?
            if len(self.value_map[constructor_type]) > 0:
                # Yes, use it.
                constructor, _constructor_loc = self.value_map[constructor_type][0]
            else:
                # No, extract one from a reference to an instance.
                instance, _instance_loc = self.value_map[instance_type][0]
                constructor = type(instance)

            self.globals[constructor_type.name] = constructor_type

            synthesizer = self._synthesizer()
            ast = synthesizer.assign_local(constructor_type.name, constructor)
            synthesizer.finalize()
            self._inject(ast)

            for attr in constructor_type.attributes:
                if types.is_function(constructor_type.attributes[attr]):
                    synthesizer = self._synthesizer()
                    ast = synthesizer.assign_attribute(constructor, attr,
                                                       getattr(constructor, attr))
                    synthesizer.finalize()
                    self._inject(ast)

        # After we have found all functions, synthesize a module to hold them.
        source_buffer = source.Buffer("", "<synthesized>")
        self.typedtree = asttyped.ModuleT(
            typing_env=self.globals, globals_in_scope=set(),
            body=self.typedtree, loc=source.Range(source_buffer, 0, 0))

    def _inject(self, node):
        self.typedtree.insert(self.inject_at, node)
        self.inject_at += 1

    def _synthesizer(self, expanded_from=None):
        return ASTSynthesizer(expanded_from=expanded_from,
                              type_map=self.type_map,
                              value_map=self.value_map,
                              quote_function=self._quote_function)

    def _quote_embedded_function(self, function):
        if not hasattr(function, "artiq_embedded"):
            raise ValueError("{} is not an embedded function".format(repr(function)))

        # Extract function source.
        embedded_function = function.artiq_embedded.function
        source_code = textwrap.dedent(inspect.getsource(embedded_function))
        filename = embedded_function.__code__.co_filename
        module_name, _ = os.path.splitext(os.path.basename(filename))
        first_line = embedded_function.__code__.co_firstlineno

        # Extract function environment.
        host_environment = dict()
        host_environment.update(embedded_function.__globals__)
        cells = embedded_function.__closure__
        cell_names = embedded_function.__code__.co_freevars
        host_environment.update({var: cells[index] for index, var in enumerate(cell_names)})

        # Parse.
        source_buffer = source.Buffer(source_code, filename, first_line)
        parsetree, comments = parse_buffer(source_buffer, engine=self.engine)
        function_node = parsetree.body[0]

        # Mangle the name, since we put everything into a single module.
        function_node.name = "{}.{}".format(module_name, function_node.name)

        # Normally, LocalExtractor would populate the typing environment
        # of the module with the function name. However, since we run
        # ASTTypedRewriter on the function node directly, we need to do it
        # explicitly.
        self.globals[function_node.name] = types.TVar()

        # Memoize the function before typing it to handle recursive
        # invocations.
        self.functions[function] = function_node.name

        # Rewrite into typed form.
        asttyped_rewriter = StitchingASTTypedRewriter(
            engine=self.engine, prelude=self.prelude,
            globals=self.globals, host_environment=host_environment,
            quote=self._quote)
        return asttyped_rewriter.visit(function_node)

    def _function_loc(self, function):
        filename = function.__code__.co_filename
        line     = function.__code__.co_firstlineno
        name     = function.__code__.co_name

        source_line = linecache.getline(filename, line)
        while source_line.lstrip().startswith("@"):
            line += 1
            source_line = linecache.getline(filename, line)

        column = re.search("def", source_line).start(0)
        source_buffer = source.Buffer(source_line, filename, line)
        return source.Range(source_buffer, column, column)

    def _function_def_note(self, function):
        return diagnostic.Diagnostic("note",
            "definition of function '{function}'",
            {"function": function.__name__},
            self._function_loc(function))

    def _extract_annot(self, function, annot, kind, call_loc, is_syscall):
        if not isinstance(annot, types.Type):
            if is_syscall:
                note = diagnostic.Diagnostic("note",
                    "in system call here", {},
                    call_loc)
            else:
                note = diagnostic.Diagnostic("note",
                    "in function called remotely here", {},
                    call_loc)
            diag = diagnostic.Diagnostic("error",
                "type annotation for {kind}, '{annot}', is not an ARTIQ type",
                {"kind": kind, "annot": repr(annot)},
                self._function_loc(function),
                notes=[note])
            self.engine.process(diag)

            return types.TVar()
        else:
            return annot

    def _type_of_param(self, function, loc, param, is_syscall):
        if param.annotation is not inspect.Parameter.empty:
            # Type specified explicitly.
            return self._extract_annot(function, param.annotation,
                                       "argument '{}'".format(param.name), loc,
                                       is_syscall)
        elif is_syscall:
            # Syscalls must be entirely annotated.
            diag = diagnostic.Diagnostic("error",
                "system call argument '{argument}' must have a type annotation",
                {"argument": param.name},
                self._function_loc(function))
            self.engine.process(diag)
        elif param.default is not inspect.Parameter.empty:
            # Try and infer the type from the default value.
            # This is tricky, because the default value might not have
            # a well-defined type in APython.
            # In this case, we bail out, but mention why we do it.
            ast = self._quote(param.default, None)

            def proxy_diagnostic(diag):
                note = diagnostic.Diagnostic("note",
                    "expanded from here while trying to infer a type for an"
                    " unannotated optional argument '{argument}' from its default value",
                    {"argument": param.name},
                    loc)
                diag.notes.append(note)

                diag.notes.append(self._function_def_note(function))

                self.engine.process(diag)

            proxy_engine = diagnostic.Engine()
            proxy_engine.process = proxy_diagnostic
            Inferencer(engine=proxy_engine).visit(ast)
            IntMonomorphizer(engine=proxy_engine).visit(ast)

            return ast.type
        else:
            # Let the rest of the program decide.
            return types.TVar()

    def _quote_foreign_function(self, function, loc, syscall):
        signature = inspect.signature(function)

        arg_types = OrderedDict()
        optarg_types = OrderedDict()
        for param in signature.parameters.values():
            if param.kind not in (inspect.Parameter.POSITIONAL_ONLY,
                                  inspect.Parameter.POSITIONAL_OR_KEYWORD):
                # We pretend we don't see *args, kwpostargs=..., **kwargs.
                # Since every method can be still invoked without any arguments
                # going into *args and the slots after it, this is always safe,
                # if sometimes constraining.
                #
                # Accepting POSITIONAL_ONLY is OK, because the compiler
                # desugars the keyword arguments into positional ones internally.
                continue

            if param.default is inspect.Parameter.empty:
                arg_types[param.name] = self._type_of_param(function, loc, param,
                                                            is_syscall=syscall is not None)
            elif syscall is None:
                optarg_types[param.name] = self._type_of_param(function, loc, param,
                                                               is_syscall=syscall is not None)
            else:
                diag = diagnostic.Diagnostic("error",
                    "system call argument '{argument}' must not have a default value",
                    {"argument": param.name},
                    self._function_loc(function))
                self.engine.process(diag)

        if signature.return_annotation is not inspect.Signature.empty:
            ret_type = self._extract_annot(function, signature.return_annotation,
                                           "return type", loc, is_syscall=syscall is not None)
        elif syscall is None:
            diag = diagnostic.Diagnostic("error",
                "function must have a return type annotation to be called remotely", {},
                self._function_loc(function))
            self.engine.process(diag)
            ret_type = types.TVar()
        else: # syscall is not None
            diag = diagnostic.Diagnostic("error",
                "system call must have a return type annotation", {},
                self._function_loc(function))
            self.engine.process(diag)
            ret_type = types.TVar()

        if syscall is None:
            function_type = types.TRPCFunction(arg_types, optarg_types, ret_type,
                                               service=self.object_map.store(function))
            function_name = "rpc${}".format(function_type.service)
        else:
            function_type = types.TCFunction(arg_types, ret_type,
                                             name=syscall)
            function_name = "ffi${}".format(function_type.name)

        self.globals[function_name] = function_type
        self.functions[function] = function_name

        return function_name, function_type

    def _quote_function(self, function, loc):
        if function in self.functions:
            function_name = self.functions[function]
            return function_name, self.globals[function_name]

        if hasattr(function, "artiq_embedded"):
            if function.artiq_embedded.function is not None:
                # Insert the typed AST for the new function and restart inference.
                # It doesn't really matter where we insert as long as it is before
                # the final call.
                function_node = self._quote_embedded_function(function)
                self._inject(function_node)
                return function_node.name, self.globals[function_node.name]
            elif function.artiq_embedded.syscall is not None:
                # Insert a storage-less global whose type instructs the compiler
                # to perform a system call instead of a regular call.
                return self._quote_foreign_function(function, loc,
                                                    syscall=function.artiq_embedded.syscall)
            else:
                assert False
        else:
            # Insert a storage-less global whose type instructs the compiler
            # to perform an RPC instead of a regular call.
            return self._quote_foreign_function(function, loc,
                                                syscall=None)

    def _quote(self, value, loc):
        synthesizer = self._synthesizer(loc)
        node = synthesizer.quote(value)
        synthesizer.finalize()
        return node