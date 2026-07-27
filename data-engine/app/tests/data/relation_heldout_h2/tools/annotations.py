# -*- coding: utf-8 -*-
"""Anotacion H2 (un solo pase). ref = (libro, pagina, frase_inicial, ventana) del pool muestreado."""

# (src_key, workspace, ref, titulo_corto)
SOURCES = [
    ("src-01", "trudvang", ("trudvang_master", 24, 7, 3), "Stormi une a los stormlandeses"),
    ("src-02", "trudvang", ("trudvang_master", 29, 5, 3), "Los viraneses y Gave"),
    ("src-03", "trudvang", ("trudvang_master", 20, 26, 3), "Arkland en Jarngand"),
    ("src-04", "trudvang", ("trudvang_master", 19, 2, 3), "Whote, creador de Yggdrasil"),
    ("src-05", "trudvang", ("trudvang_master", 19, 11, 3), "Shurd, senor oscuro"),
    ("src-06", "trudvang", ("trudvang_master", 53, 33, 2), "Kivala acude a salvar a Thorgarth"),
    ("src-07", "trudvang", ("trudvang_master", 27, 22, 3), "Los paises de Vastermark"),
    ("src-08", "trudvang", ("trudvang_master", 29, 8, 3), "El ovus de Vastermark"),
    ("src-09", "trudvang", ("trudvang_player", 29, 25, 3), "Los stormkelts y la fe gerbanica"),
    ("src-10", "trudvang", ("trudvang_player", 21, 11, 2), "Las tribus salvajes"),
    ("src-11", "trudvang", ("trudvang_player", 213, 18, 2), "El noaj Huglakk y su reliquia"),
    ("src-12", "trudvang", ("trudvang_player", 195, 14, 2), "La misa de Olmunda en Firidge"),
    ("src-13", "trudvang", ("trudvang_player", 184, 3, 1), "Los nueve reyes de Yggdrasil"),
    ("src-14", "vampiro", ("v20", 24, 29, 2), "Cain y los Ancianos en Enoch"),
    ("src-15", "vampiro", ("v20", 397, 6, 2), "Los Capadocios en la sociedad Cainita"),
    ("src-16", "vampiro", ("v20", 67, 1, 2), "Ventrue, el Clan de los Reyes"),
    ("src-17", "vampiro", ("v20", 418, 23, 3), "El Viejo Clan Tzimisce"),
    ("src-18", "vampiro", ("v20", 358, 8, 2), "Vampiros y Lupinos"),
    ("src-19", "vampiro", ("v20", 350, 13, 2), "Ingrid Bauer, la Doncella de Hierro"),
    ("src-20", "vampiro", ("v20", 288, 25, 1), "Vinculo de Sangre y Jyhad"),
    ("src-21", "vampiro", ("v20", 18, 27, 1), "Principes y autoridades de la Estirpe"),
    ("src-22", "vampiro", ("v20", 275, 9, 3), "Diablerie y el odio de la Camarilla"),
    ("src-23", "vampiro", ("v20", 394, 13, 2), "La guia de Muricia"),
    ("src-24", "vampiro", ("v20", 33, 16, 1), "Los Clanes Fundadores"),
    ("src-25", "vampiro", ("v20", 241, 40, 3), "Veronica y su rival Giselle"),
    ("src-26", "leyenda", ("transcripcion", 0, 193, 0), "Magistrados de los clanes en el comedor"),
    ("src-27", "leyenda", ("transcripcion", 0, 1777, 0), "Llega un diplomatico Leon"),
    ("src-28", "leyenda", ("transcripcion", 0, 1566, 0), "La ceremonia del te"),
    ("src-29", "leyenda", ("transcripcion", 0, 1374, 0), "Invitacion a la biblioteca"),
    ("src-30", "leyenda", ("transcripcion", 0, 1404, 0), "Registros retirados del clan Grulla"),
    ("src-31", "leyenda", ("transcripcion", 0, 414, 0), "Hanzo y sus dos companeros"),
    ("src-32", "leyenda", ("transcripcion", 0, 997, 0), "Hanzo pide ensenanza a la profesora"),
    ("src-33", "leyenda", ("transcripcion", 0, 1022, 0), "Los venenos y los magistrados esmeralda"),
    ("src-34", "trudvang", ("trudvang_master", 47, 10, 2), "RUIDO: reglas de armas a dos manos"),
    ("src-35", "vampiro", ("v20", 96, 8, 3), "RUIDO: la Tecnica Artesania"),
    ("src-36", "leyenda", ("transcripcion", 0, 672, 0), "RUIDO: los cinco elementos"),
]

# rel: (src, subj_txt, subj_id, subj_type, PRED, obj_txt, obj_id, obj_type, evid,
#       negated, temporal, epistemic, direction, decision, notas)
S, O, U = "SUBJECT_TO_OBJECT", "OBJECT_TO_SUBJECT", "UNDIRECTED"
A, R, V = "ACCEPT", "REJECT", "REVIEW"
REL = [
 ("src-01", "Stormi", "stormi", "Character", "CAUSED",
  "unió a los stormlandeses en un solo pueblo", "union-stormlandeses", "Event",
  "fue el dios Stormi, las ofrendas de sangre y la creencia en la Gran Tormenta lo que unió a los stormlandeses en un solo pueblo",
  False, "PAST", "ASSERTED", S, A, "Causalidad explicita con estructura escindida 'fue X lo que Y'. Stormi es una de tres causas citadas."),
 ("src-01", "los stormlandeses", "stormlandeses", "Faction", "MEMBER_OF",
  "un culto a sus antepasados", "culto-antepasados", "Concept",
  "la mayoría de los stormlandeses mantenían un culto a sus antepasados",
  False, "ENDED", "ASSERTED", S, A, "Pertenencia religiosa TERMINADA: 'antes de adoptar el gerbanismo' marca el fin."),

 ("src-02", "Los viraneses", "viraneses", "Faction", "CREATED",
  "una sociedad basada en gran medida en la religión", "sociedad-viranesa", "Concept",
  "Los viraneses crearon una sociedad basada en gran medida en la religión",
  False, "PAST", "ASSERTED", S, A, "Creacion explicita en voz activa."),
 ("src-02", "los viraneses", "viraneses", "Faction", "PARTICIPATED_IN",
  "muchas guerras y batallas", "guerras-de-gave", "Event",
  "han librado muchas guerras y batallas en nombre de Gave",
  False, "PAST", "ASSERTED", S, A, "Sujeto ELIDIDO en la coordinada: 'han librado' comparte sujeto con la oracion anterior."),

 ("src-03", "Arkland", "arkland", "Location", "LOCATED_IN",
  "Jarngand occidental", "jarngand", "Location",
  "Arkland es el nombre del reino situado en Jarngand occidental",
  False, "ATEMPORAL", "ASSERTED", S, A, "Localizacion explicita mediante participio 'situado en'."),
 ("src-03", "los arks salvajes", "arks", "Faction", "LIVES_IN",
  "Arkland", "arkland", "Location",
  "el reino situado en Jarngand occidental, habitado por los arks salvajes",
  False, "ONGOING", "ASSERTED", O, A, "VOZ PASIVA: el habitante es el complemento agente, no el sujeto sintactico."),

 ("src-04", "Whote", "whote", "Character", "CREATED",
  "el antiguo árbol Yggdrasil", "yggdrasil", "Object",
  "Whote Es el creador del antiguo árbol Yggdrasil",
  False, "PAST", "ASSERTED", S, A, "Nominalizacion 'es el creador de' en vez de verbo. Nota: el salto de linea del PDF deja 'Whote Es' con mayuscula."),
 ("src-04", "Whote", "whote", "Character", "PARENT_OF",
  "toda la humanidad", "humanidad", "Faction",
  "padre de toda la humanidad",
  False, "ATEMPORAL", "ASSERTED", S, A, "Filiacion mitologica por nominalizacion coordinada ('creador de... y padre de...')."),

 ("src-05", "Shurd", "shurd", "Character", "ENEMY_OF",
  "los dioses", "dioses", "Faction",
  "Luchó contra los dioses en la Era de los Sueños",
  False, "PAST", "ASSERTED", U, A, "Enemistad SIN lexico de enemistad: se infiere de 'lucho contra'. Simetrica."),
 ("src-05", "Shurd", "shurd", "Character", "LEADS",
  "grandes bestias como los dragones", "grandes-bestias", "Character",
  "Shurd es un señor oscuro y maestro de grandes bestias como los dragones",
  False, "ATEMPORAL", "ASSERTED", S, V, "AMBIGUO: 'maestro de' aqui es amo/senor, no mentor. Un segundo anotador podria poner OWNS o MENTOR_OF; por eso REVIEW."),

 ("src-06", "Kivala", "kivala", "Character", "ALLIED_WITH",
  "Thorgarth", "thorgarth", "Character",
  "una compañera que el stormlandés creyó haber perdido. Se trata de Kivala",
  False, "ONGOING", "ASSERTED", U, V, "La relacion se expresa por APOSICION a distancia: 'una companera' -> 'Se trata de Kivala'. El otro extremo es un epiteto ('el stormlandes') que hay que resolver a Thorgarth."),
 ("src-06", "Kivala", "kivala", "Character", "MEMBER_OF",
  "illmalaini", "illmalaini", "Faction",
  "Kivala, una tejevitner illmalaini de pelo blanco",
  False, "ATEMPORAL", "ASSERTED", S, A, "Gentilicio como adjetivo pospuesto, sin verbo."),

 ("src-07", "Silvtronder", "silvtronder", "Location", "MEMBER_OF",
  "Vastermark", "vastermark", "Location",
  "Los países que constituyen el núcleo de Vastermark son Silvtronder, Bysente, Carlonne, Viranne, Tronland y Vistergalp",
  False, "ONGOING", "ASSERTED", S, A, "ENUMERACION de seis miembros en atributo de copulativa; la relacion va del atributo al sujeto."),
 ("src-07", "Vistergalp", "vistergalp", "Location", "MEMBER_OF",
  "Vastermark", "vastermark", "Location",
  "Los países que constituyen el núcleo de Vastermark son Silvtronder, Bysente, Carlonne, Viranne, Tronland y Vistergalp",
  False, "ONGOING", "ASSERTED", S, A, "Ultimo elemento de la misma enumeracion: prueba de explosion de pares."),

 ("src-08", "el ovus", "ovus", "Character", "LEADS",
  "Vastermark", "vastermark", "Location",
  "el ovus, el líder espiritual de Vastermark",
  False, "PRESENT", "ASSERTED", S, A, "Liderazgo por aposicion nominal, no por verbo."),

 ("src-09", "Los stormkelts", "stormkelts", "Faction", "MEMBER_OF",
  "la fe gerbánica", "fe-gerbanica", "Concept",
  "se han entregado a la fe gerbánica para proteger a los débiles",
  False, "ONGOING", "ASSERTED", S, V, "AMBIGUO: 'entregarse a una fe' es adhesion religiosa; MEMBER_OF es la aproximacion mas cercana de esta ontologia. REVIEW por eso."),

 ("src-10", "los amures", "amures", "Faction", "LIVES_IN",
  "las montañas del noroeste", "montanas-noroeste", "Location",
  "los amures que viven en las montañas del noroeste",
  False, "ONGOING", "ASSERTED", S, A, "Oracion de relativo dentro de una enumeracion de tribus."),
 ("src-10", "los amures", "amures", "Faction", "MEMBER_OF",
  "salvajes", "salvajes", "Faction",
  "se les llama salvajes a un conjunto de distintas tribus: los amures que viven en las montañas del noroeste",
  False, "ATEMPORAL", "ASSERTED", S, V, "Pertenencia por DOS PUNTOS tras 'un conjunto de distintas tribus'. Tambien podria leerse como ALIAS_OF colectivo: REVIEW."),

 ("src-11", "El noaj Huglakk", "huglakk", "Character", "OWNS",
  "un cráneo humano", "craneo-humano", "Object",
  "El noaj Huglakk lleva un cráneo humano firmemente atado a su hombro izquierdo",
  False, "ONGOING", "ASSERTED", S, A, "'llevar atado' como posesion/porte. Ejemplo de reglas, pero narrativo."),

 ("src-12", "Olmunda", "olmunda", "Character", "PARTICIPATED_IN",
  "una misa", "misa-firidge", "Event",
  "Olmunda decide oficiar una misa, ayudada por cuatro sacerdotes más",
  False, "PRESENT", "ASSERTED", S, A, "Participacion como oficiante. 'decide oficiar' NO la vuelve intencional: la frase siguiente afirma que la misa ocurre."),
 ("src-12", "La misa", "misa-firidge", "Event", "LOCATED_IN",
  "el santuario de Firidge", "santuario-firidge", "Location",
  "La misa dura una hora y tiene lugar en el santuario de Firidge",
  False, "PRESENT", "ASSERTED", S, A, "Localizacion de un EVENTO, no de una entidad fisica."),

 ("src-13", "el primer rey de Majnjord", "primer-rey-majnjord", "Character", "LEADS",
  "Majnjord", "majnjord", "Location",
  "el primer rey de Majnjord",
  False, "PAST", "ASSERTED", S, A, "Liderazgo dentro de un sintagma nominal sin verbo alguno."),
 ("src-13", "Yggdrasil", "yggdrasil", "Object", "PARENT_OF",
  "los nueve reyes", "nueve-reyes", "Faction",
  "uno de los nueve reyes nacidos de Yggdrasil",
  False, "PAST", "ASSERTED", O, V, "Filiacion INVERTIDA: el progenitor aparece como complemento de 'nacidos de'. REVIEW porque la filiacion es mitologica, no biologica."),

 ("src-14", "Caín", "cain", "Character", "PARENT_OF",
  "estos inefables Ancianos", "ancianos-enoch", "Faction",
  "Caín Abrazó a estos inefables Ancianos",
  False, "PAST", "ASSERTED", S, V, "'Abrazar' es el termino del sistema para engendrar un vampiro (sire). PARENT_OF es la aproximacion; REVIEW porque exige conocer el argot del manual."),
 ("src-14", "estos inefables Ancianos", "ancianos-enoch", "Faction", "LIVES_IN",
  "la gran ciudad de Enoch", "enoch", "Location",
  "para que moraran con él en la gran ciudad de Enoch",
  False, "PAST", "ASSERTED", S, A, "Subordinada final con verbo en subjuntivo ('moraran')."),

 ("src-15", "los Capadocios", "capadocios", "Faction", "MEMBER_OF",
  "la sociedad Cainita", "sociedad-cainita", "Faction",
  "los Capadocios estaban firmemente arraiga - dos en la sociedad Cainita de su época",
  False, "ENDED", "ASSERTED", S, A, "Pertenencia TERMINADA ('estaban', 'de su epoca'). La evidencia contiene un artefacto de extraccion del PDF ('arraiga - dos')."),

 ("src-16", "Ventrue", "ventrue", "Faction", "ALIAS_OF",
  "el Clan de los Re - yes", "clan-de-los-reyes", "Faction",
  "han sido durante mucho tiempo el Clan de los Re - yes entre los Vástagos",
  False, "ONGOING", "ASSERTED", U, A, "Alias explicito. El sujeto ('Ventrue') esta a dos frases de distancia y el alias contiene un artefacto de guionado del PDF."),

 ("src-17", "El Viejo Clan Tzimisce", "viejo-clan-tzimisce", "Faction", "MEMBER_OF",
  "Desalmados", "desalmados", "Faction",
  "El Viejo Clan Tzimisce es un pequeño grupo de Desalmados",
  False, "ATEMPORAL", "ASSERTED", S, A, "Copulativa de pertenencia, caso facil."),

 ("src-18", "los vampiros", "vampiros", "Faction", "ENEMY_OF",
  "los Lupinos", "lupinos", "Faction",
  "Cuando los vampiros y los Lupinos se topan, es casi seguro que acabará en un baño de sangre",
  False, "ONGOING", "ASSERTED", U, V, "Enemistad IMPLICITA: hay que inferirla de 'acabara en un bano de sangre'. REVIEW: un anotador estricto la dejaria fuera."),

 ("src-19", "Ingrid Bauer", "ingrid-bauer", "Character", "ALIAS_OF",
  "“La Doncella de Hierro Original”", "doncella-hierro", "Character",
  "la otrora austríaca Ingrid Bauer, conocida a sus espaldas como “La Doncella de Hierro Original”",
  False, "ONGOING", "ASSERTED", U, A, "Alias explicito con comillas tipograficas y marcador 'conocida como'."),

 ("src-20", "algunos Ancianos", "ancianos", "Faction", "OWNS",
  "docenas de Vástagos influyentes", "vastagos-influyentes", "Faction",
  "se dice que algunos Ancianos mantienen secretamente esclavizados a docenas de Vástagos influyentes",
  False, "ONGOING", "RUMORED", S, V, "RUMOR explicito ('se dice que'). Debe quedar en REVIEW, nunca en ACCEPT."),

 ("src-21", "Muchos Príncipes", "principes", "Faction", "MEMBER_OF",
  "la Estirpe", "estirpe", "Faction",
  "Muchos Príncipes y otras autoridades de la Estirpe",
  False, "ONGOING", "ASSERTED", S, A, "Pertenencia por coordinacion 'X y otras autoridades de Y'."),

 ("src-22", "los Antiguos de la Camarilla", "antiguos-camarilla", "Faction", "ENEMY_OF",
  "los vampiros del Sabbat", "vampiros-sabbat", "Faction",
  "otra razón más por la que los Antiguos de la Camarilla los o dian tanto",
  False, "ONGOING", "ASSERTED", U, A, "El objeto es el PRONOMBRE cliticio 'los', que hay que resolver a 'los vampiros del Sabbat'. Artefacto de PDF: 'o dian'."),
 ("src-22", "los vampiros del Sabbat", "vampiros-sabbat", "Faction", "PARTICIPATED_IN",
  "Diablerie", "diablerie", "Event",
  "Se dice que los vampiros del Sabbat tienen libertad para cometer Diablerie",
  False, "ONGOING", "RUMORED", S, V, "RUMOR explicito ('Se dice que') sobre una practica, no sobre un hecho puntual."),

 ("src-23", "Muricia", "muricia", "Character", "MENTOR_OF",
  "las Ahrimanes", "ahrimanes", "Faction",
  "para representar la guía de Muricia",
  False, "PAST", "ASSERTED", S, V, "Mentoria por NOMINALIZACION ('la guia de X') y en un texto de reglas de creacion de personaje. REVIEW."),

 ("src-24", "Brujah", "brujah", "Faction", "MEMBER_OF",
  "sus Clanes Fundadores", "clanes-fundadores", "Faction",
  "la mayoría proceden de sus Clanes Fundadores: Brujah, Gangrel, Malkavian, Nosferatu, Toreador, Tremere y Ventrue",
  False, "ATEMPORAL", "ASSERTED", S, A, "Enumeracion de SIETE miembros tras dos puntos: el peor caso de explosion de pares del corpus."),
 ("src-24", "Ventrue", "ventrue", "Faction", "MEMBER_OF",
  "sus Clanes Fundadores", "clanes-fundadores", "Faction",
  "la mayoría proceden de sus Clanes Fundadores: Brujah, Gangrel, Malkavian, Nosferatu, Toreador, Tremere y Ventrue",
  False, "ATEMPORAL", "ASSERTED", S, A, "Mismo listado; 'Ventrue' aparece tambien en src-16 con otro papel."),

 ("src-25", "Veronica", "veronica", "Character", "ENEMY_OF",
  "Giselle", "giselle", "Character",
  "fastidiar a su rival, una Ventrue llamada Giselle",
  False, "ONGOING", "ASSERTED", U, A, "'su rival' + aposicion con el nombre. Ejemplo de reglas con narrativa dentro."),
 ("src-25", "Giselle", "giselle", "Character", "MEMBER_OF",
  "Ventrue", "ventrue", "Faction",
  "una Ventrue llamada Giselle",
  False, "ONGOING", "ASSERTED", S, A, "Clan como sustantivo apositivo antepuesto al nombre."),

 ("src-26", "los magistrados del clan gruya", "magistrados-grulla", "Faction", "MEMBER_OF",
  "clan gruya", "clan-grulla", "Faction",
  "los los magistrados del clan gruya están separados en una mesa",
  False, "PRESENT", "ASSERTED", S, A, "HABLA: sin puntuacion ni mayusculas, con repeticion de articulo ('los los') y el clan Grulla transcrito como 'gruya' por el ASR."),
 ("src-26", "los magistrados del clan león", "magistrados-leon", "Faction", "MEMBER_OF",
  "clan león", "clan-leon", "Faction",
  "los magistrados del clan león están separados en otra",
  False, "PRESENT", "ASSERTED", S, A, "Segundo grupo de la misma frase; el objeto elidido ('en otra [mesa]') no afecta a esta relacion."),

 ("src-27", "un diplomático", "diplomatico-leon", "Character", "MEMBER_OF",
  "león", "clan-leon", "Faction",
  "es es un diplomático león vestido con",
  False, "PRESENT", "ASSERTED", S, V, "HABLA: tartamudeo ('es es'), clan en minuscula y usado como adjetivo, y la frase queda CORTADA al final del fragmento. REVIEW."),

 ("src-28", "daiqui", "daiki", "Character", "OWNS",
  "la habitación", "habitacion-daiki", "Location",
  "en la habitación en la habitación de daiqui",
  False, "PRESENT", "ASSERTED", S, V, "HABLA: autocorreccion con repeticion literal del sintagma. El personaje Daiki aparece transcrito 'daiqui' (en otras partes 'daiki'): la MISMA entidad tiene dos formas de superficie en el mismo documento."),

 ("src-29", "daiki", "daiki", "Character", "LOCATED_IN",
  "la biblioteca", "biblioteca", "Location",
  "que te parece si me me acompañas a la biblioteca",
  False, "FUTURE", "INTENDED", S, V, "INTENCION en forma de invitacion. El otro extremo de la relacion es un 'me' deictico cuyo referente NO esta en el fragmento: por eso solo se anota a Daiki."),

 ("src-30", "esos registros", "registros-grulla", "Object", "LOCATED_IN",
  "la biblioteca", "biblioteca", "Location",
  "buscar en la biblioteca registro sobre el clan gruyas",
  False, "PAST", "ASSERTED", S, V, "HABLA: 'registro' en singular por 'registros', 'gruyas' por Grulla. La frase siguiente los declara RETIRADOS, asi que la localizacion ya no es vigente."),

 ("src-31", "Hanzo", "hanzo", "Character", "ALLIED_WITH",
  "Daiki", "daiki", "Character",
  "cuando llegan tus dos compañeros? ¿Vosotros dos? Daiki, Hasu",
  False, "PRESENT", "ASSERTED", U, V, "Requiere resolver 'tus dos companeros' con los nombres que aparecen DESPUES, tras dos preguntas intercaladas."),
 ("src-31", "Hanzo", "hanzo", "Character", "ALLIED_WITH",
  "Hasu", "hasu", "Character",
  "cuando llegan tus dos compañeros? ¿Vosotros dos? Daiki, Hasu",
  False, "PRESENT", "ASSERTED", U, V, "Segundo companero del mismo par."),

 ("src-32", "la profesora", "profesora", "Character", "MENTOR_OF",
  "Hanzo", "hanzo", "Character",
  "Hanzo, te quedas solo con la profesora",
  False, "PRESENT", "ASSERTED", O, V, "La mentoria se establece en la frase pero el PEDIDO ('que compartisse conmigo algo de su sabiduria') es lo que la motiva. Direccion invertida respecto al orden de aparicion."),

 ("src-33", "ningún magistrado esmeralda", "magistrado-esmeralda", "Character", "OWNS",
  "los venenos", "venenos", "Object",
  "que ningún magistrado esmeralda debe utilizar, como son los venenos",
  True, "ONGOING", "ASSERTED", S, A, "NEGACION mediante cuantificador negativo ('ningun') + verbo modal deontico. La relacion existe en el texto pero NEGADA."),

 ("src-34", "Armas Ligeras a Una Mano", "armas-ligeras", "Concept", "NO_RELATION",
  "Armas Arrojadizas", "armas-arrojadizas", "Concept",
  "Las especialidades Armas Ligeras a Una Mano, Armas Pesadas a Una Mano y Armas Arrojadizas se pueden aprender con ambas manos",
  False, "ATEMPORAL", "ASSERTED", U, R, "CENTINELA de ruido: dos elementos de una lista de reglas que COOCURREN sin ninguna relacion narrativa entre si."),
 ("src-35", "Artesanía", "artesania", "Concept", "NO_RELATION",
  "la pericia mecánica", "pericia-mecanica", "Concept",
  "Artesanía te permite trabajar en campos como la carpintería, el trabajo con cuero, los textiles o incluso la pericia mecánica",
  False, "ATEMPORAL", "ASSERTED", U, R, "CENTINELA de ruido: texto de reglas en segunda persona, sin entidades de ficcion."),
 ("src-36", "el agua", "agua", "Concept", "NO_RELATION",
  "el aire", "aire", "Concept",
  "que el agua sea algo más fluido, que el aire",
  False, "ATEMPORAL", "ASSERTED", U, R, "CENTINELA de ruido en HABLA: enumeracion de los cinco elementos, coocurrencia sin relacion."),
]

# Etiquetas de cobertura linguistica por fuente (metadato para cases/cases.json).
TAGS = {
    "src-01": [
        "causalidad",
        "estructura-escindida",
        "pertenencia-terminada"
    ],
    "src-02": [
        "creacion",
        "sujeto-elidido",
        "coordinacion"
    ],
    "src-03": [
        "geografia",
        "voz-pasiva",
        "complemento-agente"
    ],
    "src-04": [
        "nominalizacion",
        "filiacion-mitologica",
        "artefacto-pdf"
    ],
    "src-05": [
        "enemistad-implicita",
        "simetrica",
        "predicado-ambiguo"
    ],
    "src-06": [
        "aposicion-a-distancia",
        "epiteto",
        "gentilicio"
    ],
    "src-07": [
        "enumeracion",
        "explosion-de-pares",
        "copulativa"
    ],
    "src-08": [
        "aposicion",
        "liderazgo"
    ],
    "src-09": [
        "adhesion-religiosa",
        "predicado-ambiguo"
    ],
    "src-10": [
        "oracion-de-relativo",
        "dos-puntos",
        "tribus"
    ],
    "src-11": [
        "posesion",
        "texto-de-reglas-con-narrativa"
    ],
    "src-12": [
        "evento",
        "localizacion-de-evento",
        "ejemplo-de-manual"
    ],
    "src-13": [
        "sintagma-sin-verbo",
        "filiacion-invertida"
    ],
    "src-14": [
        "argot-del-sistema",
        "filiacion",
        "subjuntivo"
    ],
    "src-15": [
        "pertenencia-terminada",
        "artefacto-pdf"
    ],
    "src-16": [
        "alias",
        "sujeto-a-distancia",
        "artefacto-pdf"
    ],
    "src-17": [
        "copulativa",
        "caso-facil"
    ],
    "src-18": [
        "enemistad-implicita",
        "simetrica"
    ],
    "src-19": [
        "alias",
        "comillas-tipograficas"
    ],
    "src-20": [
        "rumor",
        "posesion"
    ],
    "src-21": [
        "coordinacion",
        "pertenencia"
    ],
    "src-22": [
        "pronombre-cliticio",
        "rumor",
        "artefacto-pdf",
        "enemistad"
    ],
    "src-23": [
        "mentoria",
        "nominalizacion",
        "texto-de-reglas"
    ],
    "src-24": [
        "enumeracion-larga",
        "explosion-de-pares",
        "entidad-repetida"
    ],
    "src-25": [
        "ejemplo-de-manual",
        "enemistad",
        "clan-apositivo"
    ],
    "src-26": [
        "habla-sin-puntuacion",
        "error-asr-nombre-propio",
        "repeticion"
    ],
    "src-27": [
        "habla-sin-puntuacion",
        "tartamudeo",
        "frase-cortada",
        "minusculas"
    ],
    "src-28": [
        "habla-sin-puntuacion",
        "autocorreccion",
        "dos-formas-de-la-misma-entidad"
    ],
    "src-29": [
        "habla-sin-puntuacion",
        "intencion-futura",
        "deixis-sin-referente"
    ],
    "src-30": [
        "habla-sin-puntuacion",
        "error-asr-nombre-propio",
        "localizacion-caduca"
    ],
    "src-31": [
        "habla-sin-puntuacion",
        "correferencia-pospuesta",
        "simetrica"
    ],
    "src-32": [
        "habla-sin-puntuacion",
        "mentoria",
        "direccion-invertida"
    ],
    "src-33": [
        "habla-sin-puntuacion",
        "negacion-por-cuantificador"
    ],
    "src-34": [
        "centinela-ruido",
        "reglas"
    ],
    "src-35": [
        "centinela-ruido",
        "reglas",
        "segunda-persona"
    ],
    "src-36": [
        "centinela-ruido",
        "habla-sin-puntuacion"
    ]
}
