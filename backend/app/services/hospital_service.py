hospitals = [
    {"id":"H001","name":"Apollo Hospital","area":"Andheri","distance":5,"available_beds":10,"icu_beds":4,"ambulance":True,"trauma_center":True},
    {"id":"H002","name":"Fortis Hospital","area":"Bandra","distance":7,"available_beds":8,"icu_beds":3,"ambulance":True,"trauma_center":True},
    {"id":"H003","name":"Lilavati Hospital","area":"Bandra West","distance":9,"available_beds":6,"icu_beds":2,"ambulance":True,"trauma_center":True},
    {"id":"H004","name":"Kokilaben Hospital","area":"Andheri West","distance":6,"available_beds":12,"icu_beds":5,"ambulance":True,"trauma_center":True},
    {"id":"H005","name":"Nanavati Hospital","area":"Vile Parle","distance":8,"available_beds":9,"icu_beds":3,"ambulance":True,"trauma_center":True},
    {"id":"H006","name":"Hinduja Hospital","area":"Mahim","distance":10,"available_beds":7,"icu_beds":2,"ambulance":True,"trauma_center":True},
    {"id":"H007","name":"Jaslok Hospital","area":"Pedder Road","distance":12,"available_beds":11,"icu_beds":4,"ambulance":True,"trauma_center":True},
    {"id":"H008","name":"Bombay Hospital","area":"Marine Lines","distance":14,"available_beds":13,"icu_beds":5,"ambulance":True,"trauma_center":True},
    {"id":"H009","name":"Breach Candy Hospital","area":"Breach Candy","distance":15,"available_beds":8,"icu_beds":3,"ambulance":True,"trauma_center":True},
    {"id":"H010","name":"Wockhardt Hospital","area":"Mumbai Central","distance":11,"available_beds":10,"icu_beds":4,"ambulance":True,"trauma_center":True},
    {"id":"H011","name":"SevenHills Hospital","area":"Marol","distance":7,"available_beds":15,"icu_beds":6,"ambulance":True,"trauma_center":True},
    {"id":"H012","name":"Hiranandani Hospital","area":"Powai","distance":13,"available_beds":9,"icu_beds":3,"ambulance":True,"trauma_center":True},
    {"id":"H013","name":"S. L. Raheja Hospital","area":"Mahim","distance":10,"available_beds":8,"icu_beds":2,"ambulance":True,"trauma_center":False},
    {"id":"H014","name":"KEM Hospital","area":"Parel","distance":9,"available_beds":20,"icu_beds":8,"ambulance":True,"trauma_center":True},
    {"id":"H015","name":"Sion Hospital","area":"Sion","distance":8,"available_beds":18,"icu_beds":7,"ambulance":True,"trauma_center":True},
    {"id":"H016","name":"Cooper Hospital","area":"Juhu","distance":6,"available_beds":14,"icu_beds":5,"ambulance":True,"trauma_center":True},
    {"id":"H017","name":"Bhatia Hospital","area":"Tardeo","distance":13,"available_beds":7,"icu_beds":2,"ambulance":True,"trauma_center":False},
    {"id":"H018","name":"Saifee Hospital","area":"Charni Road","distance":12,"available_beds":9,"icu_beds":3,"ambulance":True,"trauma_center":True},
    {"id":"H019","name":"Holy Family Hospital","area":"Bandra","distance":9,"available_beds":11,"icu_beds":4,"ambulance":True,"trauma_center":False},
    {"id":"H020","name":"Global Hospital","area":"Parel","distance":11,"available_beds":10,"icu_beds":4,"ambulance":True,"trauma_center":True},
]


def get_best_hospital():
    available = [h for h in hospitals if h["available_beds"] > 0]

    return min(
        available,
        key=lambda h: (
            h["distance"],
            -h["available_beds"],
            -h["icu_beds"]
        ),
    )