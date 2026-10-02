
#Aca vamos a hacer todas las comparaciones exactas respecto a lo q esta en la base de conocimientos
#Si emiliano nos dijese q ellos prefieren algo 100 % agentico esto se iria a la skill de duplicados del agente
#igual q lo de validar_entrada, a la skill validator.
#Es xq las comprobaciones de parte del servidor son mas economicas q ejecutar skills con el agente

#IMPORTANTE : a las  estructuras para comparar voy a guardar en disco, pars q sea mas rapido
#efectuar dsps las comparaciones y para q no tenga q volver a hacerlo cada vez q se reinicia el servidor

#NINGUNA DE ESTAS FUNCIONES PROBABLEMENTE SEA ASYNC AUNQUE EL SERVER CUANDO LAS INVOQUE USE ASYNC!

#IMPORTANTE : normalizar con slugify el titulo primero de lo q recibo
from my_agent.server.discourse import client
from slugify import slugify
#Comparar respecto a los del diccionario de titulos_slug
#Si hay coincidencia tendria q pasar la url para q dsps el server pueda indicar q ya esta y ofrecer actualizar
#Si pasa esta validacion va a comparar el codigo hash de la descripcion q recibo respecto a
#la q esta en la tabla hash q genere de las entradas
#Si pasa esa validación se utiliza recien ahi lo de embeddings de transformar el texto en un vector nuemrico
# y despues aplicar lo de coseno entre vectores!

#La gracia va a estar en despues darle estas herramientas a algun IDE agentico, decirle ok aplicame esto a x entradas
# y para las q queden en un umbral medio ambiguo genera tus propias reglas de como detectar duplicados
#Revisar que sean casos q no expongan vulnerabilidades de parte de ellos si o si antes de pasarselas al ide

#Quizas hay comparaciones semanticas o de procesamiento del lenguaje q el propio agent pude hacer

