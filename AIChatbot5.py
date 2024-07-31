import openai
import pyodbc
from docx import Document
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Set up your OpenAI API key
openai.api_key = 'Replace with your actual API Key'  # Replace with your actual OpenAI API key

# Initialize MSSQL connection
server = 'LAPTOP-1GK9IP67\\SQLEXPRESS'  # Replace with your MSSQL server name
database = 'fyp_patient'  # Replace with your MSSQL database name
cnxn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER='+server+';DATABASE='+database+';Trusted_Connection=yes;')
cursor = cnxn.cursor()

# Initialize the state dictionary to keep track of the conversation
conversation_state = {}

import pandas as pd

import pandas as pd

def read_prompts_from_excel(file_path):
    # Load the entire Excel file
    xls = pd.ExcelFile(file_path)
    prompts = {}
    
    # Iterate over each sheet name in the Excel file
    for sheet_name in xls.sheet_names:
        # Read the current sheet into a DataFrame
        df = pd.read_excel(xls, sheet_name)
        
        # Check if the 'AI' column exists in the current sheet
        if 'AI' in df.columns:
            # Extract the questions from the 'AI' column, dropping any NaN values
            questions = df['AI'].dropna().tolist()
            
            # Store the questions in the dictionary with the sheet name as the key
            prompts[sheet_name.lower()] = questions
    
    # Return the dictionary
    return prompts

# Define the symptoms and their respective questions by reading from the Excel file
file_path = 'C:\\Y3S1\\FYP\\Interactions to be sent to SOI.xlsx'
symptoms_prompts = read_prompts_from_excel(file_path)



def generate_response(prompt, user_input):
    combined_input = f"Q: {prompt}\nA: {user_input}\nQ:"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0,
        messages=[
            {"role": "system", "content": "You are an AI assistant integrated into a digital pharmacy platform. Your primary role is to collect patient information through a conversation on telegram and relay this information to the pharmacist"},
            {"role": "user", "content": combined_input}
        ]
    )
    return response['choices'][0]['message']['content']

def generate_symptom_questions(symptoms_prompts):
    prompt = (
        f"Use the following prompt to generate similar or better questions to better understand what symptom the user is facing:\n\n{symptoms_prompts}\n\n"
        "Ensure the new questions are clear, specific, and cover various aspects such as onset, duration, severity, associated symptoms, impact on daily life, medical history, lifestyle factors, environmental triggers, and recent changes. "
        "Rephrase existing questions for better clarity if needed. Provide 5 to 10 questions."
    )
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a medical assistant asking relevant symptom-specific questions to better understand what the user is facing."},
            {"role": "user", "content": prompt}
        ]
    )
    questions = response['choices'][0]['message']['content'].split('\n')
    return [q for q in questions if q.strip()]


def generate_dynamic_questions(symptom_description):
    prompt = (
        f"Generate questions to better understand the symptoms based on the following description:\n\n{symptom_description}\n\n"
        "Ensure the new questions are clear, specific, and cover various aspects such as onset, duration, severity, associated symptoms, impact on daily life, medical history, lifestyle factors, environmental triggers, and recent changes. "
        "Rephrase existing questions for better clarity if needed. Provide 5 to 10 questions."
    )
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a medical assistant asking relevant symptom-specific questions to better understand what the user is facing. Ask symptom-specific questions and limit it to a maximum of 10 questions, or a minimum of 5 questions."},
            {"role": "user", "content": prompt}
        ]
    )
    questions = response['choices'][0]['message']['content'].split('\n')
    return [q for q in questions if q.strip()]


def summarize_symptoms(user_data):
    symptoms_description = "\n".join([f"{question} {answer}" for question, answer in user_data.items()])
    prompt = f"Summarize the following symptoms into 100 words:\n{symptoms_description}"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a medical assistant summarizing the conversation for professional healthcare physicians to make diagnosis more efficiently."},
            {"role": "user", "content": prompt}
        ]
    )
    return response['choices'][0]['message']['content']

def generate_next_default_question(state, user_input):
    index = state['default_prompt_index']
    questions = state['default_questions']

    if index == 0:  # "Are you buying medicine for yourself?"
        if user_input.lower() in ['no', 'nope']:
            state['who_is_patient'] = 'others'
            return "Who is the medication for? (Person receiving medication is the patient)"
        else:
            index += 1
            state['default_prompt_index'] = index
            return questions[index]  # "Okay, do you have any drug allergies?"

    if index == 1:  # "Okay, do you have any drug allergies?"
        if user_input.lower() in ['yes', 'yep', 'yup']:
            state['user_data']['allergy'] = 'yes'
            index += 1
            state['default_prompt_index'] = index
            return questions[index]  # "What allergies do you have?"
        else:
            state['user_data']['allergy'] = 'no'
            index += 2
            state['default_prompt_index'] = index
            return questions[index]  # "Do you have any existing medical conditions (Yes/No) (e.g. High blood pressure, diabetes,etc.)?"

    if index == 2:  # "What allergies do you have?"
        state['user_data']['allergy_details'] = user_input
        index += 1
        state['default_prompt_index'] = index
        return questions[index]  # "Do you have any existing medical conditions (Yes/No) (e.g. High blood pressure, diabetes,etc.)?"

    if index == 3:  # "Do you have any existing medical conditions (Yes/No) (e.g. High blood pressure, diabetes,etc.)?"
        if user_input.lower() in ['yes', 'yep', 'yup']:
            index += 1
            state['default_prompt_index'] = index
            return questions[index]  # "What existing medical conditions do you have? (Please state your existing medical conditions)"
        else:
            state['using_default_questions'] = False
            return 'Thank you for the information. Please describe the symptoms you are experiencing. Kindly input one symptom first. We will address other symptoms further on in this conversation!'

    if index == 4:  # "What existing medical conditions do you have? (Please state your existing medical conditions)"
        state['user_data']['existing_condition'] = user_input
        index += 1
        state['default_prompt_index'] = index
        return questions[index]  # "Are you currently taking any medication for your existing medical conditions? (Yes/No)"

    if index == 5:  # "Are you currently taking any medication for your existing medical conditions? (Yes/No)"
        if user_input.lower() in ['yes', 'yep', 'yup']:
            index += 1
            state['default_prompt_index'] = index
            return questions[index]  # "What medications are you taking for your existing medical condition? (Please state the medication.)"
        else:
            state['using_default_questions'] = False
            return 'Thank you for the information. Please describe the symptoms you are experiencing. Kindly input one symptom first. We will address other symptoms further on in this conversation!'

    if index == 6:  # "What medications are you taking for your existing medical condition? (Please state the medication.)"
        state['user_data']['medication'] = user_input
        state['using_default_questions'] = False
        return 'Thank you for the information. Please describe the symptoms you are experiencing. Kindly input one symptom first. We will address other symptoms further on in this conversation!'
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_state[chat_id] = {
        'current_prompt_index': 0,
        'default_prompt_index': 0,
        'symptom': None,
        'user_data': {},
        'user_replies': [],  # Store user replies
        'nested_symptom': None,
        'dynamic_questions': [],
        'default_questions': [
            "Are you buying medicine for yourself? (Yes/No)",
            "Okay, do you have any drug allergies? (Yes/No) ", 
            "What allergies do you have? (Please state your allergy)",
            "Do you have any existing medical conditions (Yes/No) (e.g. High blood pressure, diabetes,etc.)?",
            "What existing medical conditions do you have? (Please state your existing medical conditions)",
            "Are you currently taking any medication for your existing medical conditions? (Yes/No)",
            "What medications are you taking for your existing medical condition? (Please state the medication.)"
        ],
        'using_default_questions': True,  # Track if using default questions
        'asking_for_more_symptoms': False,  # Track if asking for more symptoms
        'current_symptoms': [],
        'additional_symptoms': [],
        'who_is_patient': 'self',
        'awaiting_rating': False,  # Track if waiting for rating
        'summary': '',  # Store summary
        'rating': None  # Store rating
    }
    await update.message.reply_text('Hello! Welcome to Wellchem Pharmacy. I am your AI assistant here to help you today. Could you give me the patient name?')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    user_input = update.message.text.lower()

    if chat_id not in conversation_state:
        conversation_state[chat_id] = {
            'current_prompt_index': 0,
            'default_prompt_index': 0,
            'symptom': None,
            'user_data': {},
            'user_replies': [],  # Store user replies
            'nested_symptom': None,
            'dynamic_questions': [],
            'default_questions': [
                "Are you buying medicine for yourself? (Yes/No)", 
                "Okay, do you have any drug allergies? (Yes/No)", 
                "What allergies do you have? (Please state your allergies)", 
                "Do you have any existing medical conditions (Yes/No) (e.g. High blood pressure, diabetes,etc.)?", 
                "What existing medical conditions do you have? (Please state your existing medical conditions)", 
                "Are you currently taking any medication for your existing medical conditions? (Yes/No)", 
                "What medications are you taking for your existing medical condition? (Please state the medication.)" 
            ],
            'using_default_questions': True,
            'asking_for_more_symptoms': False,
            'current_symptoms': [],
            'additional_symptoms': [],
            'who_is_patient': 'self',
            'awaiting_rating': False,
            'summary': '',
            'rating': None
        }

    state = conversation_state[chat_id]

    if state['awaiting_rating']:
        try:
            rating = int(user_input)
            if 1 <= rating <= 5:
                state['rating'] = rating
                await update.message.reply_text("Thank you for your rating!")
                insert_customer_summary(state['user_data'], state['current_symptoms'], state['additional_symptoms'], state['summary'], state['who_is_patient'], state['rating'], state['user_replies'])
                del conversation_state[chat_id]  # End the conversation
                return
            else:
                await update.message.reply_text("Please provide a rating from 1 to 5.")
        except ValueError:
            await update.message.reply_text("Please provide a valid rating from 1 to 5.")
        return

    if state['symptom'] is None:
        # Collect basic information
        if 'name' not in state['user_data']:
            state['user_data']['name'] = user_input
            state['user_replies'].append(user_input)
            await update.message.reply_text("Could you please provide your age?")
            return

        if 'age' not in state['user_data']:
            state['user_data']['age'] = user_input
            state['user_replies'].append(user_input)
            await update.message.reply_text(state['default_questions'][state['default_prompt_index']])
            return

        # Process default questions
        if state['using_default_questions']:
            default_questions = state['default_questions']
            index = state['default_prompt_index']
            if index < len(default_questions):
                question_key = f'question_{index + 1}'
                state['user_data'][question_key] = user_input
                state['user_replies'].append(user_input)

                next_question = generate_next_default_question(state, user_input)

                if next_question:
                    await update.message.reply_text(next_question)
                    return
                else:
                    state['using_default_questions'] = False
                    await update.message.reply_text('Thank you for the information. Please describe the symptoms you are experiencing. Kindly input one symptom first. We will address other symptoms further on in this conversation!')
                    return

    # Handle symptom-specific questions
    if state['symptom'] is None:
        for keyword in symptoms_prompts:
            if keyword in user_input:
                state['symptom'] = keyword
                state['current_symptoms'].append(user_input)
                state['dynamic_questions'] = generate_symptom_questions(symptoms_prompts[keyword])
                state['user_replies'].append(user_input)
                await update.message.reply_text(f'You mentioned {keyword}. Let\'s get more details about this symptom.')
                await update.message.reply_text(state['dynamic_questions'][0])
                return
        
        state['dynamic_questions'] = generate_dynamic_questions(user_input)
        state['symptom'] = 'dynamic'
        state['current_symptoms'].append(user_input)
        state['user_replies'].append(user_input)
        await update.message.reply_text(state['dynamic_questions'][0])
        return

    symptom = state['symptom']
    index = state['current_prompt_index']
    questions = state['dynamic_questions']

    if index < len(questions):
        state['user_data'][questions[index]] = user_input
        state['user_replies'].append(user_input)
        
        if "can you specify what other symptoms you are experiencing" in questions[index].lower():
            for keyword in symptoms_prompts:
                if keyword in user_input:
                    state['nested_symptom'] = keyword
                    state['current_prompt_index'] = 0
                    state['dynamic_questions'] = generate_symptom_questions(keyword, symptoms_prompts[keyword])
                    state['additional_symptoms'].append(user_input)
                    await update.message.reply_text(f"Let's address your {keyword} symptoms.")
                    await update.message.reply_text(state['dynamic_questions'][0])
                    return

        index += 1
        state['current_prompt_index'] = index

        if state['nested_symptom'] is not None:
            questions = state['dynamic_questions']
            if index < len(questions):
                await update.message.reply_text(questions[index])
            else:
                state['nested_symptom'] = None
                state['current_prompt_index'] = 0
                await update.message.reply_text("Thank you for your information! Here is what I got:")
                for question, answer in state['user_data'].items():
                    await update.message.reply_text(f"{question}: {answer}")
                state['user_data'] = {}
        else:
            if index < len(questions):
                await update.message.reply_text(questions[index])
            else:
                await update.message.reply_text("Do you have any other symptoms?")
                state['asking_for_more_symptoms'] = True
                return

    if state['asking_for_more_symptoms']:
        if user_input in ['yes', 'yeah', 'yep', 'yup']:
            await update.message.reply_text("Please describe your other symptoms.")
            state['symptom'] = None
            state['current_prompt_index'] = 0
            state['asking_for_more_symptoms'] = False
        else:
            summary = summarize_symptoms(state['user_data'])
            state['summary'] = summary
            await update.message.reply_text("Thank you for your information! Here is a summary of the symptoms you are experiencing:")
            await update.message.reply_text(summary)

            if len(state['current_symptoms']) > 1:
                state['additional_symptoms'] = state['current_symptoms'][1:]
                state['current_symptoms'] = [state['current_symptoms'][0]]

            await update.message.reply_text("On a scale of 1 to 5, how would you rate your experience with this service?")
            state['awaiting_rating'] = True
            return

def flatten_list(nested_list):
    flat_list = []
    for item in nested_list:
        if isinstance(item, list):
            flat_list.extend(item)
        else:
            flat_list.append(item)
    return flat_list

def insert_customer_summary(user_data, current_symptoms, additional_symptoms, summary, who_is_patient, rating, user_replies):
    additional_symptoms = flatten_list(additional_symptoms)
    
    # Prepare SQL query
    sql_query = """
    INSERT INTO patient_info 
    (who_is_patient, patient_name, patient_age, patient_drug_allergy, patient_existing_condition, existing_med_intake, current_symptom, additional_symptoms, summary, ratings)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # Extract data from user_replies list
    if who_is_patient == "self":
        patient_name = user_replies[0]
        patient_age = user_replies[1]
        patient_drug_allergy = user_replies[4] if user_replies[3] in ['yes', 'yea', 'yup'] else user_replies[3]
        patient_existing_condition = user_replies[6] if user_replies[5] in ['yes', 'yea', 'yup'] else user_replies[5] 
        if user_replies[4] in ['no', 'none', 'nope']:
            patient_existing_condition=user_replies[4]
        existing_med_intake = 'NIL' if patient_existing_condition in ['no', 'none', 'nope'] or user_replies[7] in ['no', 'none', 'nope'] or user_replies[6] in ['no', 'none', 'nope']  else user_replies[8] #should go one before
        if user_replies[3] in ['no', 'none', 'nope'] and user_replies[4] in ['no', 'none', 'nope']:
            existing_med_intake='NIL'
        if user_replies[6] in ['yes', 'yea', 'yup']:
            existing_med_intake=user_replies[7]
        current_symptom = current_symptoms[0]  # Get the first current symptom
        additional_symptoms_str = ', '.join(additional_symptoms)
    else:
        patient_name = user_replies[0]
        patient_age = user_replies[1]
        patient_drug_allergy = user_replies[5] if user_replies[4] in ['yes', 'yea', 'yup'] else user_replies[4]
        patient_existing_condition = user_replies[7] if user_replies[6] in ['yes', 'yea', 'yup'] else user_replies[6] 
        if user_replies[5] in ['no', 'none', 'nope']:
            patient_existing_condition=user_replies[5]
        existing_med_intake = 'NIL' if patient_existing_condition in ['no', 'none', 'nope'] or user_replies[8] in ['no', 'none', 'nope'] or user_replies[7] in ['no', 'none', 'nope']  else user_replies[9] #should go one before
        if user_replies[4] in ['no', 'none', 'nope'] and user_replies[5] in ['no', 'none', 'nope']:
            existing_med_intake='NIL'
        if user_replies[7] in ['yes', 'yea', 'yup']:
            existing_med_intake=user_replies[8]
        current_symptom = current_symptoms[0]  # Get the first current symptom
        additional_symptoms_str = ', '.join(additional_symptoms)

    # Log the SQL query and data
    print("Executing SQL query:")
    print(sql_query)
    print("Data:")
    print((who_is_patient, patient_name, patient_age, patient_drug_allergy, patient_existing_condition, existing_med_intake, current_symptom, additional_symptoms_str, summary, rating))

    # Execute SQL query
    try:
        cursor.execute(sql_query, (
            who_is_patient, patient_name, patient_age, patient_drug_allergy, patient_existing_condition, existing_med_intake, current_symptom, additional_symptoms_str, summary, rating
        ))
        cnxn.commit()  # Commit the transaction
        print("Data inserted successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")

# Create the application and add the handlers
app = Application.builder().token("Replace with your Telegram API Key").build()  # Replace with your actual bot token

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Add the /stop command handler
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Stopping the bot. Thank you for using our service!")
    app.stop()

app.add_handler(CommandHandler("stop", stop))

# Start the bot
app.run_polling()


