from my_agent.server.discourse import client


#IMPORTANTE : a las estructuras para comparar voy a guardar en disco, pars q sea mas rapido
#efectuar dsps las comparaciones y para q no tenga q volver a hacerlo cada vez q se reinicia el servidor

#NINGUNA DE ESTAS FUNCIONES PROBABLEMENTE SEA ASYNC AUNQUE EL SERVER CUANDO LAS INVOQUE USE ASYNC!



#IMPORTANTE : normalizar con slugify el titulo primero de lo q recibo
from my_agent.server.discourse import client
#Comparar respecto a los del diccionario de titulos_slug
#Si hay coincidencia tendria q pasar la url para q dsps el server pueda indicar q ya esta y ofrecer actualizar
#Si pasa esta validacion va a comparar el codigo hash de la descripcion q recibo respecto a
#la q esta en la tabla hash q genere de las entradas
#Si pasa esa validación se utiliza recien ahi lo de embeddings de transformar el texto en un vector nuemrico
# y despues aplicar lo de coseno entre vectores!

#La gracia va a estar en despues darle estas herramientas a algun IDE agentico, decirle ok aplicame esto a x entradas
# y para las q queden en un umbral medio ambiguo genera tus propias reglas de como detectar duplicados
#Revisar que sean casos q no expongan vulnerabilidades de parte de ellos  (Ppor eso el ide agentico estaria bueno q solo tenga el .py
#y que acceda a bc finnegans como un user comun



#1 normalizo
#deberia guardar en otro lado un
#Mas adelante si esto es poco performante podria hacer una rutina en c que haga un sort x el titulo de la entrada
#dsps un binary search, hbria q parsear el .json a algun formato q c pueda leer
#Por eso estaria ueno probar con una libreria en py que use C para leer