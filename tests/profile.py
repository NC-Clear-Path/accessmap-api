from shapely.geometry import Point
from accessmapapi.routing import costs, route


origin = Point([-122.32508034811278, 47.645040425347645])
destination = Point([-122.279865, 47.676246])

route_response = route.dijkstra(origin, destination,
                                cost_fun_gen=costs.cost_fun_generator)
