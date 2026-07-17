import requests

HANDLE = "vk04"

def get_recent_submissions(handle, count=5):
    url = f"https://codeforces.com/api/user.status?handle={handle}&count={count}"
    response = requests.get(url)
    data = response.json()

    if data["status"] != "OK":
        print(data)
        return []

    return data["result"]

def main():
    submissions = get_recent_submissions(HANDLE, count=5)

    for sub in submissions:
        problem_name = sub["problem"]["name"]
        verdict = sub["verdict"]
        language = sub["programmingLanguage"]
        print(f"{problem_name} | {verdict} | {language}")

if __name__ == "__main__":
    main()